#!/usr/bin/env python3
"""Retrain a compact UrbanMind reference model on real 2023 data and produce
the PM2.5 predictions required by the station-holdout evaluation (R1.2).

Architecture (reference-scale echo of the manuscript's world model):
  - station graph per city, Gaussian-kernel k-NN adjacency (row-normalised);
  - 2 rounds of graph message passing over a shared hidden space;
  - FiLM conditioning of every layer on the dynamic context vector
    (city-level daily meteorology from ERA5-derived open-meteo archive,
    day-of-year encoding, training-station daily mean, city embedding);
  - static node covariates: position (km), elevation, distance to centre.

Protocol (mirrors the manuscript's temporal split):
  - training window Jan-Aug 2023, early-stopping validation Sep-Oct,
    test window Nov-Dec (the station-holdout evaluation window);
  - holdout stations (fixed-seed strata from station_holdout_eval.py) are
    excluded from training loss AND from every input statistic; Singapore is
    handled by leave-one-region-out (5 folds, one model per fold);
  - the dynamic "training-station daily mean" input never touches holdout
    stations, so no holdout observation leaks into any input or target.

Output: data/holdout/urbanmind_prediction_request_filled.csv, ready for
  python3 scripts/station_holdout_eval.py --score-predictions <that file>
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
import station_holdout_eval as she  # noqa: E402

ROOT = she.ROOT
RAW = she.RAW
OUT = she.OUT
SEED = she.SEED
YEAR_START, YEAR_END = date(2023, 1, 1), date(2023, 12, 31)
TRAIN_END = date(2023, 8, 31)
VAL_END = date(2023, 10, 31)

METEO_FILES = {"NYC": "meteo_nyc.json", "Nanjing": "meteo_nanjing.json",
               "Singapore": "meteo_singapore.json"}
METEO_VARS = ["temperature_2m_mean", "wind_speed_10m_max", "precipitation_sum",
              "surface_pressure_mean", "shortwave_radiation_sum",
              "relative_humidity_2m_mean"]

torch.manual_seed(SEED)
np.random.seed(SEED)


# ---------------------------------------------------------------- loading --

def load_meteo(name):
    j = json.loads((RAW / METEO_FILES[name]).read_text())["daily"]
    days = [date.fromisoformat(t) for t in j["time"]]
    m = np.column_stack([np.array(j[v], dtype=float) for v in METEO_VARS])
    m = np.nan_to_num(m, nan=0.0)
    return {d: m[i] for i, d in enumerate(days)}


def load_city_year(name):
    if name == "NYC":
        return she.load_nyc(YEAR_START, YEAR_END)
    if name == "Nanjing":
        return she.load_nanjing(YEAR_START, YEAR_END)
    return she.load_singapore(YEAR_START, YEAR_END)


def holdout_from_eval_window(name):
    """Reproduce the exact holdout sets of station_holdout_eval.py (defined on
    the Nov-Dec network with the fixed seed)."""
    if name == "NYC":
        obs, coords = she.load_nyc()
    elif name == "Nanjing":
        obs, coords = she.load_nanjing()
    else:
        obs, coords = she.load_singapore()
    coords = coords.loc[sorted(set(obs["station"]) & set(coords.index))]
    elev = json.loads((RAW / "elevations.json").read_text())
    _, xy = she.covariates(coords, elev)
    return she.holdout_splits(coords, xy, loo=(name == "Singapore"))


# ------------------------------------------------------------------ model --

class GraphFiLM(nn.Module):
    """Graph message passing with FiLM conditioning on the dynamic context."""

    def __init__(self, n_static, n_dyn, hidden=64, layers=2):
        super().__init__()
        self.embed_s = nn.Linear(n_static, hidden)
        self.embed_d = nn.Linear(n_dyn, hidden)
        self.layers = layers
        self.self_w = nn.ModuleList(nn.Linear(hidden, hidden) for _ in range(layers))
        self.msg_w = nn.ModuleList(nn.Linear(hidden, hidden) for _ in range(layers))
        self.film = nn.ModuleList(nn.Linear(n_dyn, 2 * hidden) for _ in range(layers))
        self.head = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(),
                                  nn.Linear(hidden, 1))

    def forward(self, xs, xd, a_hat):
        # xs: [nodes, Fs]; xd: [days, Fd]; a_hat: [nodes, nodes]
        h = torch.relu(self.embed_s(xs)[None, :, :] + self.embed_d(xd)[:, None, :])
        for i in range(self.layers):
            gamma, beta = self.film[i](xd).chunk(2, dim=-1)  # [days, hidden]
            m = torch.einsum("nm,dmh->dnh", a_hat, h)
            h = torch.relu(self.self_w[i](h) + self.msg_w[i](m))
            h = h * (1 + gamma[:, None, :]) + beta[:, None, :]
        return self.head(h).squeeze(-1)  # [days, nodes]


def build_adjacency(xy, k=5):
    n = len(xy)
    d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    sigma = np.median(d[d > 0]) if n > 1 else 1.0
    a = np.exp(-(d ** 2) / (2 * sigma ** 2))
    np.fill_diagonal(a, 0.0)
    if n > k + 1:  # keep k nearest neighbours
        for i in range(n):
            drop = np.argsort(a[i])[:-k]
            a[i, drop] = 0.0
    a = a / np.maximum(a.sum(axis=1, keepdims=True), 1e-9)
    return a


# ------------------------------------------------------------ city tensors --

def city_tensors(name, obs, coords, elev, meteo, train_stations, city_onehot):
    """Build [days, nodes] observation matrix and input tensors. The dynamic
    daily-mean input uses training stations only."""
    coords = coords.loc[sorted(set(obs["station"]) & set(coords.index))]
    stations = list(coords.index)
    days = sorted(obs["date"].unique())
    day_idx = {d: i for i, d in enumerate(days)}
    st_idx = {s: i for i, s in enumerate(stations)}

    y = np.full((len(days), len(stations)), np.nan)
    for _, r in obs.iterrows():
        if r["station"] in st_idx:
            y[day_idx[r["date"]], st_idx[r["station"]]] = r["pm25"]

    x_cov, xy = she.covariates(coords, elev)
    xs = np.column_stack([xy, x_cov])  # x, y, elev, dist

    tr_cols = [st_idx[s] for s in train_stations if s in st_idx]
    with np.errstate(invalid="ignore"):
        tr_mean = np.nanmean(y[:, tr_cols], axis=1)
    tr_mean = pd.Series(tr_mean).ffill().bfill().values
    prev_mean = np.roll(tr_mean, 1)
    prev_mean[0] = tr_mean[0]

    met = np.array([meteo.get(d, np.zeros(len(METEO_VARS))) for d in days])
    doy = np.array([d.timetuple().tm_yday for d in days])
    xd = np.column_stack([met,
                          np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365),
                          tr_mean, prev_mean,
                          np.tile(city_onehot, (len(days), 1))])
    return stations, days, y, xs, xd, xy


def standardise(arr, mean, std):
    return (arr - mean) / np.maximum(std, 1e-6)


# ------------------------------------------------------------------- train --

def run_fold(fold, cities_raw, meteos, elev, request_rows):
    """Train one joint model. `fold` gives the Singapore holdout region index;
    NYC and Nanjing always use their fixed stratified holdout."""
    holdouts = {"NYC": HOLDOUTS["NYC"][0], "Nanjing": HOLDOUTS["Nanjing"][0],
                "Singapore": HOLDOUTS["Singapore"][fold]}
    onehots = {"NYC": [1, 0, 0], "Nanjing": [0, 1, 0], "Singapore": [0, 0, 1]}

    packs = {}
    for name, obs, coords in cities_raw:
        train_st = [s for s in coords.index if s not in holdouts[name]]
        stations, days, y, xs, xd, xy = city_tensors(
            name, obs, coords, elev, meteos[name], train_st, onehots[name])
        train_cols = np.array([i for i, s in enumerate(stations) if s in train_st])
        hold_cols = np.array([i for i, s in enumerate(stations) if s in holdouts[name]])
        d_arr = np.array(days)
        tr_rows = np.array([i for i, d in enumerate(d_arr) if d <= TRAIN_END])
        va_rows = np.array([i for i, d in enumerate(d_arr) if TRAIN_END < d <= VAL_END])
        te_rows = np.array([i for i, d in enumerate(d_arr) if d > VAL_END])

        # normalisation statistics from training window, training stations only
        y_tr = y[np.ix_(tr_rows, train_cols)]
        y_mu, y_sd = np.nanmean(y_tr), np.nanstd(y_tr)
        xs_n = standardise(xs, xs.mean(axis=0), xs.std(axis=0))
        xd_mu, xd_sd = xd[tr_rows].mean(axis=0), xd[tr_rows].std(axis=0)
        xd_n = standardise(xd, xd_mu, xd_sd)

        packs[name] = dict(
            stations=stations, days=days, y=y, y_mu=y_mu, y_sd=y_sd,
            xs=torch.tensor(xs_n, dtype=torch.float32),
            xd=torch.tensor(xd_n, dtype=torch.float32),
            a=torch.tensor(build_adjacency(xy), dtype=torch.float32),
            train_cols=train_cols, hold_cols=hold_cols,
            tr_rows=tr_rows, va_rows=va_rows, te_rows=te_rows)

    n_static = packs["NYC"]["xs"].shape[1]
    n_dyn = packs["NYC"]["xd"].shape[1]
    model = GraphFiLM(n_static, n_dyn)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)

    def masked_mse(name, rows, cols):
        p = packs[name]
        pred = model(p["xs"], p["xd"][rows], p["a"])[:, cols]
        target = torch.tensor((p["y"][np.ix_(rows, cols)] - p["y_mu"]) / p["y_sd"],
                              dtype=torch.float32)
        mask = ~torch.isnan(target)
        if mask.sum() == 0:
            return None
        return ((pred[mask] - target[mask]) ** 2).mean()

    best_val, best_state, patience = np.inf, None, 0
    for epoch in range(3000):
        model.train()
        opt.zero_grad()
        losses = [masked_mse(n, packs[n]["tr_rows"], packs[n]["train_cols"])
                  for n in packs]
        loss = torch.stack([l for l in losses if l is not None]).mean()
        loss.backward()
        opt.step()
        if epoch % 10 == 0:
            model.eval()
            with torch.no_grad():
                vals = [masked_mse(n, packs[n]["va_rows"], packs[n]["train_cols"])
                        for n in packs]
                val = float(torch.stack([v for v in vals if v is not None]).mean())
            if val < best_val - 1e-5:
                best_val, patience = val, 0
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
            else:
                patience += 1
                if patience >= 30:
                    break
    model.load_state_dict(best_state)
    model.eval()

    # predictions at holdout stations, test window
    preds = {}
    with torch.no_grad():
        export = ["Singapore"] if fold > 0 else list(packs)
        for name in export:
            p = packs[name]
            if len(p["hold_cols"]) == 0:
                continue
            out = model(p["xs"], p["xd"][p["te_rows"]], p["a"])
            out = out[:, p["hold_cols"]].numpy() * p["y_sd"] + p["y_mu"]
            for ri, row in enumerate(p["te_rows"]):
                for ci, col in enumerate(p["hold_cols"]):
                    preds[(name, p["stations"][col], str(p["days"][row]))] = \
                        float(out[ri, ci])
    return preds, best_val


def main():
    elev = json.loads((RAW / "elevations.json").read_text())
    meteos = {n: load_meteo(n) for n in METEO_FILES}
    cities_raw = []
    for name in ("NYC", "Nanjing", "Singapore"):
        obs, coords = load_city_year(name)
        coords = coords.loc[sorted(set(obs["station"]) & set(coords.index))]
        cities_raw.append((name, obs, coords))
        print(f"{name}: {len(coords)} stations, "
              f"{obs['date'].nunique()} days, {len(obs)} obs rows")

    req = pd.read_csv(OUT / "urbanmind_prediction_request.csv",
                      dtype={"station": str})
    all_preds = {}
    n_folds = len(HOLDOUTS["Singapore"])
    for fold in range(n_folds):
        preds, val = run_fold(fold, cities_raw, meteos, elev, req)
        all_preds.update(preds)
        print(f"fold {fold}: {len(preds)} predictions, best val MSE(z) {val:.4f}")

    req["pm25_pred"] = [all_preds.get((r["city"], str(r["station"]), str(r["date"])))
                        for _, r in req.iterrows()]
    n_missing = int(req["pm25_pred"].isna().sum())
    out_path = OUT / "urbanmind_prediction_request_filled.csv"
    req.to_csv(out_path, index=False)
    print(f"\nfilled request written: {out_path} "
          f"({len(req) - n_missing}/{len(req)} rows filled)")


HOLDOUTS = {n: holdout_from_eval_window(n) for n in ("NYC", "Nanjing", "Singapore")}

if __name__ == "__main__":
    main()
