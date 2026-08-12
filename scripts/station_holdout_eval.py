#!/usr/bin/env python3
"""Station-holdout evaluation for PM2.5 gridded labels (R1.2).

Protocol (reference implementation of the manuscript's Appendix A.2 addition):
  1. Load real daily PM2.5 station observations for the Nov-Dec 2023 test
     window: NYC (EPA AQS daily PM2.5, FRM/FEM), Nanjing (CNEMC national
     stations via the quotsoft.net mirror), Singapore (NEA regional PM2.5).
  2. Withhold a stratified subset of stations (spatial k-means strata as the
     LCZ-stratification proxy; ~25 percent per city). Singapore has only five
     regional stations, so leave-one-region-out cross-validation is used.
  3. Rebuild the gridded label by regression kriging using ONLY the retained
     stations (linear regression on covariates + ordinary kriging of
     residuals, pooled exponential variogram).
  4. Report, at the withheld stations:
       - label fidelity: kriged label vs raw observations;
       - reference-model performance vs kriged labels (the proxy-label metric);
       - reference-model performance vs raw observations (the holdout metric);
     the gap between the last two quantifies label-construction inflation.

The reference model is a gradient-boosted regressor trained on the kriged
labels; substitute the UrbanMind predictions at the same station locations to
obtain the manuscript numbers.
"""

import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "holdout" / "raw"
OUT = ROOT / "data" / "holdout"
SEED = 20260812
START, END = date(2023, 11, 1), date(2023, 12, 31)

NYC_COUNTIES = {"005", "047", "061", "081", "085"}  # Bronx, Kings, NY, Queens, Richmond
NANJING_CODES = [
    "1151A", "1152A", "1153A", "1154A", "1155A", "1156A", "1157A", "1158A",
    "1159A", "3422A", "3423A", "3424A", "3425A",
]


def daterange():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- loaders --

def load_nyc():
    with zipfile.ZipFile(RAW / "daily_88101_2023.zip") as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f, dtype={"State Code": str, "County Code": str})
    df = df[(df["State Code"] == "36") & (df["County Code"].isin(NYC_COUNTIES))]
    df["Date Local"] = pd.to_datetime(df["Date Local"]).dt.date
    df = df[(df["Date Local"] >= START) & (df["Date Local"] <= END)]
    df["station"] = df["State Code"] + df["County Code"] + df["Site Num"].astype(str).str.zfill(4)
    obs = (df.groupby(["station", "Date Local"])["Arithmetic Mean"].mean()
             .rename("pm25").reset_index().rename(columns={"Date Local": "date"}))
    coords = df.groupby("station")[["Latitude", "Longitude"]].first()
    return obs, coords.rename(columns={"Latitude": "lat", "Longitude": "lon"})


def load_nanjing():
    sl = pd.read_csv(RAW / "cn_station_list.csv", header=None, skiprows=2,
                     names=["code", "lon", "lat", "name", "kind", "cid",
                            "city_cn", "city_en", "ad_cn", "ad_en", "prov_cn", "prov_en"],
                     on_bad_lines="skip")
    sl["station"] = sl["code"].astype(str).str.replace("CNA", "", regex=False) + "A"
    sl = sl[sl["station"].isin(NANJING_CODES)].set_index("station")[["lat", "lon"]]
    sl = sl.astype(float)
    rows = []
    for d in daterange():
        p = RAW / "cn" / f"china_sites_{d.strftime('%Y%m%d')}.csv"
        if not p.exists() or p.stat().st_size < 1000:
            continue
        day = pd.read_csv(p)
        day = day[day["type"] == "PM2.5"]
        for st in sl.index:
            if st in day.columns:
                v = pd.to_numeric(day[st], errors="coerce").dropna()
                if len(v) >= 12:  # require at least half of the hours
                    rows.append({"station": st, "date": d, "pm25": v.mean()})
    return pd.DataFrame(rows), sl


def load_singapore():
    meta, rows = {}, []
    for d in daterange():
        p = RAW / "sg" / f"pm25_{d.strftime('%Y%m%d')}.json"
        if not p.exists():
            continue
        j = json.loads(p.read_text())
        for m in j.get("region_metadata", []):
            meta[m["name"]] = (m["label_location"]["latitude"], m["label_location"]["longitude"])
        vals = {}
        for item in j.get("items", []):
            for reg, v in item.get("readings", {}).get("pm25_one_hourly", {}).items():
                vals.setdefault(reg, []).append(v)
        for reg, v in vals.items():
            if len(v) >= 12:
                rows.append({"station": reg, "date": d, "pm25": float(np.mean(v))})
    coords = pd.DataFrame.from_dict(meta, orient="index", columns=["lat", "lon"])
    coords.index.name = "station"
    return pd.DataFrame(rows), coords


# ------------------------------------------------------------ geo helpers --

def km_xy(coords, lat0, lon0):
    x = (coords["lon"] - lon0) * 111.32 * np.cos(np.radians(lat0))
    y = (coords["lat"] - lat0) * 110.57
    return np.column_stack([x, y])


def covariates(coords, elev):
    """Reference covariates: elevation + distance to city centre (urban-intensity
    proxy standing in for the impervious/LCZ covariates of the full pipeline)."""
    lat0, lon0 = coords["lat"].mean(), coords["lon"].mean()
    xy = km_xy(coords, lat0, lon0)
    dist = np.hypot(xy[:, 0], xy[:, 1])
    e = np.array([elev.get(s, 0.0) for s in coords.index])
    return np.column_stack([e, dist]), xy


# --------------------------------------------------------------- kriging --

def fit_variogram(res_by_day, xy, idx_map):
    """Pooled empirical semivariogram of regression residuals, exponential fit."""
    pairs, gammas = [], []
    for _, day in res_by_day:
        sts = day["station"].values
        r = day["res"].values
        ii = [idx_map[s] for s in sts]
        P = xy[ii]
        for a in range(len(sts)):
            for b in range(a + 1, len(sts)):
                pairs.append(np.hypot(*(P[a] - P[b])))
                gammas.append(0.5 * (r[a] - r[b]) ** 2)
    pairs, gammas = np.array(pairs), np.array(gammas)
    bins = np.quantile(pairs, np.linspace(0, 1, 9))
    bc, bg = [], []
    for i in range(len(bins) - 1):
        m = (pairs >= bins[i]) & (pairs < bins[i + 1])
        if m.sum() >= 5:
            bc.append(pairs[m].mean()); bg.append(gammas[m].mean())
    bc, bg = np.array(bc), np.array(bg)
    sill = float(np.max(bg)); nugget = float(max(bg[0] * 0.5, 1e-3))
    best, best_err = None, np.inf
    for rng in np.linspace(max(bc.min(), 1.0), bc.max() * 2, 60):
        g = nugget + (sill - nugget) * (1 - np.exp(-bc / rng))
        err = float(np.mean((g - bg) ** 2))
        if err < best_err:
            best, best_err = rng, err
    return nugget, sill, float(best)


def krige_day(train_xy, train_res, pred_xy, nugget, sill, rng):
    def cov(h):
        return (sill - nugget) * np.exp(-h / rng)
    n = len(train_xy)
    K = np.ones((n + 1, n + 1)); K[-1, -1] = 0.0
    for a in range(n):
        for b in range(n):
            K[a, b] = cov(np.hypot(*(train_xy[a] - train_xy[b])))
        K[a, a] = sill
    out = np.empty(len(pred_xy))
    for j, p in enumerate(pred_xy):
        k = np.ones(n + 1)
        for a in range(n):
            k[a] = cov(np.hypot(*(train_xy[a] - p)))
        try:
            w = np.linalg.solve(K, k)
        except np.linalg.LinAlgError:
            w = np.linalg.lstsq(K, k, rcond=None)[0]
        out[j] = float(w[:n] @ train_res)
    return out


# -------------------------------------------------------------- pipeline --

def evaluate_city(name, obs, coords, elev, holdout_stations=None, loo=False):
    coords = coords.loc[sorted(set(obs["station"]) & set(coords.index))]
    obs = obs[obs["station"].isin(coords.index)].copy()
    X, xy = covariates(coords, elev)
    idx_map = {s: i for i, s in enumerate(coords.index)}
    rng_state = np.random.RandomState(SEED)

    if loo:
        splits = [[s] for s in coords.index]
    else:
        k = min(3, max(1, len(coords) // 4))
        strata = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit_predict(xy)
        holdout = []
        for c in range(k):
            members = [s for s, g in zip(coords.index, strata) if g == c]
            n_hold = max(1, round(0.25 * len(members)))
            holdout += list(rng_state.choice(members, size=n_hold, replace=False))
        splits = [holdout]

    fid_p, fid_o, mdl_lab_p, mdl_lab_t, mdl_obs_p, mdl_obs_t = [], [], [], [], [], []
    for holdout in splits:
        train_st = [s for s in coords.index if s not in holdout]
        tr = obs[obs["station"].isin(train_st)].copy()
        ho = obs[obs["station"].isin(holdout)].copy()

        # regression part on covariates
        Xtr = np.array([X[idx_map[s]] for s in tr["station"]])
        reg = LinearRegression().fit(Xtr, tr["pm25"].values)
        tr["res"] = tr["pm25"].values - reg.predict(Xtr)

        nugget, sill, vrange = fit_variogram(tr.groupby("date"), xy, idx_map)

        # kriged label at holdout stations, per day
        kriged = {}
        for d, day in tr.groupby("date"):
            ii = [idx_map[s] for s in day["station"]]
            ho_d = ho[ho["date"] == d]
            if len(ho_d) == 0 or len(ii) < 3:
                continue
            jj = [idx_map[s] for s in ho_d["station"]]
            base = reg.predict(X[jj])
            resid = krige_day(xy[ii], day["res"].values, xy[jj], nugget, sill, vrange)
            for s, v in zip(ho_d["station"], base + resid):
                kriged[(s, d)] = float(v)

        merged = ho.assign(label=[kriged.get((s, d), np.nan)
                                  for s, d in zip(ho["station"], ho["date"])]).dropna()
        fid_p += list(merged["label"]); fid_o += list(merged["pm25"])

        # reference model trained on kriged labels at training stations
        feats, labels = [], []
        day_mean = tr.groupby("date")["pm25"].mean().to_dict()
        for _, r in tr.iterrows():
            i = idx_map[r["station"]]
            doy = r["date"].timetuple().tm_yday
            feats.append([xy[i, 0], xy[i, 1], X[i, 0], X[i, 1],
                          np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365),
                          day_mean[r["date"]]])
            labels.append(r["pm25"])
        gbr = GradientBoostingRegressor(random_state=SEED, n_estimators=300,
                                        max_depth=3, learning_rate=0.05)
        gbr.fit(np.array(feats), np.array(labels))

        for _, r in merged.iterrows():
            i = idx_map[r["station"]]
            doy = r["date"].timetuple().tm_yday
            f = [[xy[i, 0], xy[i, 1], X[i, 0], X[i, 1],
                  np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365),
                  day_mean.get(r["date"], np.nan)]]
            if np.isnan(f[0][-1]):
                continue
            pred = float(gbr.predict(np.array(f))[0])
            mdl_lab_p.append(pred); mdl_lab_t.append(r["label"])
            mdl_obs_p.append(pred); mdl_obs_t.append(r["pm25"])

    def metrics(p, t):
        p, t = np.array(p), np.array(t)
        return {"r2": float(r2_score(t, p)),
                "rmse": float(np.sqrt(mean_squared_error(t, p))), "n": int(len(p))}

    res = {
        "city": name,
        "n_stations": int(len(coords)),
        "n_holdout": (int(len(coords)) if loo else len(splits[0])),
        "holdout_mode": "leave-one-region-out" if loo else "stratified 25% single split",
        "holdout_stations": (list(coords.index) if loo else list(map(str, splits[0]))),
        "label_fidelity_vs_raw_obs": metrics(fid_p, fid_o),
        "reference_model_vs_gridded_label": metrics(mdl_lab_p, mdl_lab_t),
        "reference_model_vs_raw_obs": metrics(mdl_obs_p, mdl_obs_t),
    }
    res["delta_r2_label_minus_obs"] = round(
        res["reference_model_vs_gridded_label"]["r2"]
        - res["reference_model_vs_raw_obs"]["r2"], 4)
    return res


def main():
    elev = json.loads((RAW / "elevations.json").read_text()) if (RAW / "elevations.json").exists() else {}
    results = []
    nyc_obs, nyc_coords = load_nyc()
    results.append(evaluate_city("NYC", nyc_obs, nyc_coords, elev))
    nj_obs, nj_coords = load_nanjing()
    results.append(evaluate_city("Nanjing", nj_obs, nj_coords, elev))
    sg_obs, sg_coords = load_singapore()
    results.append(evaluate_city("Singapore", sg_obs, sg_coords, elev, loo=True))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "holdout_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    for r in results:
        print(f"\n{r['city']}: {r['n_stations']} stations, {r['n_holdout']} held out ({r['holdout_mode']})")
        for key in ("label_fidelity_vs_raw_obs", "reference_model_vs_gridded_label",
                    "reference_model_vs_raw_obs"):
            m = r[key]
            print(f"  {key}: R2={m['r2']:.3f} RMSE={m['rmse']:.2f} (n={m['n']})")
        print(f"  delta R2 (label - obs) = {r['delta_r2_label_minus_obs']:+.3f}")


if __name__ == "__main__":
    main()
