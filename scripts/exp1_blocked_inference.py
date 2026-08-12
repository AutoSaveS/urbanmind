#!/usr/bin/env python3
"""Blocked-bootstrap inference for Experiment 1 (R1.5, R1.6).

Implements the unified statistical protocol of the revised Section 4.5:
  - resampling units are SPATIAL BLOCKS (contiguous cell clusters obtained by
    k-means on cell coordinates within each city), never grid cells or
    training seeds;
  - all pairwise comparisons use PAIRED cluster bootstrap: one block resample
    per city per replicate, shared by every model and every domain, so the
    comparison is paired at the block level and spatial dependence within a
    block never crosses resampling units;
  - the macro-average Delta R^2 (UrbanMind minus the best-of-breed per-domain
    baseline ensemble, averaged over the 12 city-domain tasks) is reported
    with a percentile 95% CI from the same paired replicates;
  - task-level UrbanMind-vs-ensemble comparisons form one pre-declared test
    family; two-sided bootstrap p-values are Holm-corrected within the family;
  - a temporally blocked variant (contiguous windows of --temporal-days days)
    is reported alongside the spatial one.

Input: a long-format CSV/parquet with one row per (city, domain, cell, date):
  city, domain, cell_id, x, y, date, y_true, pred_urbanmind, pred_<baseline>...
  (x, y in any planar unit, used only to build spatial blocks)

Usage:
  python3 scripts/exp1_blocked_inference.py --input preds.csv
  python3 scripts/exp1_blocked_inference.py --input preds.csv \
      --ensemble "temperature:stgnn,pm25:xgboost,energy:lstm,vegetation:gcn"
  python3 scripts/exp1_blocked_inference.py --demo      # synthetic self-test

Without --ensemble, the per-domain ensemble member is the baseline with the
highest point R^2 in that domain (macro over its cities); declare the
composition explicitly to match the manuscript's best-of-breed ensemble.

Outputs (next to the input file, or data/ for --demo):
  exp1_blocked_report.json   full numeric report
  exp1_task_table.tex        12-task metric table with 95% block-bootstrap CIs
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260812
ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ metrics --

def r2(y, p):
    ss = np.sum((y - y.mean()) ** 2)
    return 1.0 - np.sum((y - p) ** 2) / ss if ss > 0 else np.nan


def rmse(y, p):
    return float(np.sqrt(np.mean((y - p) ** 2)))


def mae(y, p):
    return float(np.mean(np.abs(y - p)))


# ------------------------------------------------------------------- blocks --

def spatial_blocks(df, n_blocks, seed):
    """K-means on cell coordinates within each city -> contiguous blocks.
    Returns a Series mapping each row to 'city/block_id'."""
    from sklearn.cluster import KMeans
    labels = pd.Series(index=df.index, dtype=object)
    for city, g in df.groupby("city"):
        cells = g.drop_duplicates("cell_id")[["cell_id", "x", "y"]]
        k = min(n_blocks, len(cells))
        km = KMeans(n_clusters=k, n_init=10, random_state=seed)
        cell_block = dict(zip(cells["cell_id"],
                              km.fit_predict(cells[["x", "y"]].values)))
        labels.loc[g.index] = [f"{city}/{cell_block[c]}" for c in g["cell_id"]]
    return labels


def temporal_blocks(df, window_days):
    dates = pd.to_datetime(df["date"])
    day0 = dates.min()
    idx = ((dates - day0).dt.days // window_days).astype(int)
    return df["city"].str.cat(idx.astype(str), sep="/t")


# ---------------------------------------------------------------- bootstrap --

def paired_block_bootstrap(df, block_col, models, ensemble, n_boot, seed):
    """One block resample per city per replicate, shared across domains and
    models. Returns per-task metric draws and macro-average Delta R^2 draws."""
    rng = np.random.default_rng(seed)
    tasks = sorted(df.groupby(["city", "domain"]).groups)
    city_blocks = {c: sorted(df.loc[df["city"] == c, block_col].unique())
                   for c in df["city"].unique()}
    # index rows by block for fast resampling
    by_block = {b: g for b, g in df.groupby(block_col)}

    task_r2 = {t: {m: [] for m in models} for t in tasks}
    macro_delta = []
    for _ in range(n_boot):
        sampled = {c: rng.choice(blocks, size=len(blocks), replace=True)
                   for c, blocks in city_blocks.items()}
        deltas = []
        for city, domain in tasks:
            parts = [by_block[b] for b in sampled[city]]
            sub = pd.concat(parts)
            sub = sub[sub["domain"] == domain]
            y = sub["y_true"].values
            scores = {m: r2(y, sub[f"pred_{m}"].values) for m in models}
            for m in models:
                task_r2[(city, domain)][m].append(scores[m])
            deltas.append(scores["urbanmind"] - scores[ensemble[domain]])
        macro_delta.append(float(np.mean(deltas)))
    return task_r2, np.array(macro_delta)


def ci(draws, lo=2.5, hi=97.5):
    return [float(np.percentile(draws, lo)), float(np.percentile(draws, hi))]


def boot_pvalue(draws):
    """Two-sided percentile bootstrap p for H0: delta = 0."""
    draws = np.asarray(draws)
    p = 2 * min(np.mean(draws <= 0), np.mean(draws >= 0))
    return float(min(1.0, max(p, 1.0 / len(draws))))


def holm(pvals):
    order = np.argsort(pvals)
    m = len(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


# ------------------------------------------------------------------ analysis --

def analyse(df, models, ensemble, n_blocks, n_boot, temporal_days, seed):
    report = {"models": models, "ensemble": ensemble, "n_boot": n_boot,
              "n_blocks_per_city": n_blocks, "seed": seed}
    for scheme in ("spatial", "temporal"):
        if scheme == "spatial":
            block = spatial_blocks(df, n_blocks, seed)
        else:
            block = temporal_blocks(df, temporal_days)
        d = df.assign(_block=block)
        task_r2, macro = paired_block_bootstrap(d, "_block", models, ensemble,
                                                n_boot, seed)
        tasks = sorted(task_r2)
        # point estimates on the full data
        point, deltas_draws, pvals = {}, [], []
        for t in tasks:
            city, domain = t
            sub = df[(df["city"] == city) & (df["domain"] == domain)]
            y = sub["y_true"].values
            point[t] = {}
            for m in models:
                p = sub[f"pred_{m}"].values
                point[t][m] = {"r2": r2(y, p), "rmse": rmse(y, p),
                               "mae": mae(y, p),
                               "r2_ci": ci(task_r2[t][m])}
            dd = (np.array(task_r2[t]["urbanmind"])
                  - np.array(task_r2[t][ensemble[domain]]))
            deltas_draws.append(dd)
            pvals.append(boot_pvalue(dd))
        adj = holm(np.array(pvals))
        macro_point = float(np.mean(
            [point[t]["urbanmind"]["r2"] - point[t][ensemble[t[1]]]["r2"]
             for t in tasks]))
        report[scheme] = {
            "macro_delta_r2": macro_point,
            "macro_delta_r2_ci95": ci(macro),
            "macro_p_boot": boot_pvalue(macro),
            "tasks": {
                f"{c}/{dom}": {
                    **{m: point[(c, dom)][m] for m in models},
                    "delta_r2": point[(c, dom)]["urbanmind"]["r2"]
                                - point[(c, dom)][ensemble[dom]]["r2"],
                    "delta_r2_ci95": ci(deltas_draws[i]),
                    "p_boot": pvals[i], "p_holm": float(adj[i]),
                } for i, (c, dom) in enumerate(tasks)}}
    return report


def latex_table(report, models):
    lines = [r"\begin{tabular}{llrrrl}", r"\toprule",
             r"City & Domain & $R^2$ (UrbanMind) & $R^2$ (ensemble) & "
             r"$\Delta R^2$ & 95\% CI \\", r"\midrule"]
    for key, t in report["spatial"]["tasks"].items():
        city, domain = key.split("/")
        um, ens_r2 = t["urbanmind"]["r2"], t["delta_r2"]
        lo, hi = t["delta_r2_ci95"]
        lines.append(f"{city} & {domain} & {um:.3f} & {um - ens_r2:.3f} & "
                     f"{ens_r2:+.3f} & [{lo:+.3f}, {hi:+.3f}] \\\\")
    s = report["spatial"]
    lines += [r"\midrule",
              f"\\multicolumn{{4}}{{l}}{{Macro average}} & "
              f"{s['macro_delta_r2']:+.3f} & "
              f"[{s['macro_delta_r2_ci95'][0]:+.3f}, "
              f"{s['macro_delta_r2_ci95'][1]:+.3f}] \\\\",
              r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


# --------------------------------------------------------------------- demo --

def make_demo(seed):
    """Synthetic 3-city x 4-domain benchmark with spatially correlated fields
    and a known small UrbanMind advantage, to self-test the pipeline."""
    rng = np.random.default_rng(seed)
    rows = []
    domains = ["temperature", "pm25", "energy", "vegetation"]
    baselines = ["stgnn", "xgboost"]
    # per-domain true advantage of urbanmind over the better baseline
    adv = {"temperature": 0.10, "pm25": 0.05, "energy": -0.03,
           "vegetation": 0.04}
    for city in ("NYC", "Nanjing", "Singapore"):
        n = 20
        xs, ys = np.meshgrid(np.arange(n), np.arange(n))
        xs, ys = xs.ravel(), ys.ravel()
        base = np.sin(xs / 4) + np.cos(ys / 5) + rng.normal(0, .3, n * n)
        for domain in domains:
            field = base * rng.uniform(0.5, 2) + rng.normal(0, .2, n * n)
            for day in range(30):
                season = np.sin(2 * np.pi * day / 30)
                y = field + season + rng.normal(0, .5, n * n)
                noise = rng.normal(0, 1.0, n * n)
                preds = {"urbanmind": y + (1 - adv[domain]) * noise
                         + rng.normal(0, .1, n * n)}
                for b in baselines:
                    preds[f"{b}"] = y + noise * rng.uniform(1.0, 1.15) \
                        + rng.normal(0, .3, n * n)
                for i in range(n * n):
                    rows.append({"city": city, "domain": domain,
                                 "cell_id": f"{city}_{i}", "x": xs[i],
                                 "y": ys[i], "date": f"2023-11-{day + 1:02d}",
                                 "y_true": y[i],
                                 **{f"pred_{m}": v[i]
                                    for m, v in preds.items()}})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="long-format predictions CSV/parquet")
    ap.add_argument("--ensemble", default="",
                    help="domain:baseline pairs, e.g. 'pm25:xgboost,...'")
    ap.add_argument("--n-blocks", type=int, default=25)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--temporal-days", type=int, default=7)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--demo", action="store_true",
                    help="run the synthetic self-test")
    args = ap.parse_args()

    if args.demo:
        df = make_demo(args.seed)
        outdir = ROOT / "data"
    elif args.input:
        p = Path(args.input)
        df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
        outdir = p.parent
    else:
        raise SystemExit("provide --input or --demo")

    models = sorted(c[5:] for c in df.columns if c.startswith("pred_"))
    assert "urbanmind" in models, "need a pred_urbanmind column"
    baselines = [m for m in models if m != "urbanmind"]

    ensemble = {}
    for pair in filter(None, args.ensemble.split(",")):
        dom, base = pair.split(":")
        ensemble[dom.strip()] = base.strip()
    for dom, g in df.groupby("domain"):
        if dom not in ensemble:  # best baseline by point R^2 in this domain
            ensemble[dom] = max(
                baselines, key=lambda m: r2(g["y_true"].values,
                                            g[f"pred_{m}"].values))

    report = analyse(df, models, ensemble, args.n_blocks, args.n_boot,
                     args.temporal_days, args.seed)
    (outdir / "exp1_blocked_report.json").write_text(
        json.dumps(report, indent=2))
    (outdir / "exp1_task_table.tex").write_text(latex_table(report, models))

    for scheme in ("spatial", "temporal"):
        s = report[scheme]
        lo, hi = s["macro_delta_r2_ci95"]
        print(f"{scheme:9s} macro-average dR2 = {s['macro_delta_r2']:+.4f}  "
              f"95% CI [{lo:+.4f}, {hi:+.4f}]  p_boot = {s['macro_p_boot']:.4f}")
    n_sig = sum(t["p_holm"] < 0.05
                for t in report["spatial"]["tasks"].values())
    print(f"tasks with Holm-adjusted p < 0.05 (spatial blocks): "
          f"{n_sig}/{len(report['spatial']['tasks'])}")
    print(f"report: {outdir / 'exp1_blocked_report.json'}")


if __name__ == "__main__":
    main()
