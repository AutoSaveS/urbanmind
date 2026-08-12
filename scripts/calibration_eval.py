#!/usr/bin/env python3
"""Uncertainty calibration evaluation for UrbanMind (R2.11).

Computes, per (city, domain):
  - empirical coverage of the nominal 90% prediction interval,
  - mean interval width,
  - expected calibration error (ECE) over the quantile set Q = {0.1, ..., 0.9},
  - reliability-diagram data (nominal vs. empirical quantile levels).

Input: long-format CSV with one row per evaluated cell/day and columns
  city, domain, y_true, and EITHER
    q5, q10, q20, ..., q90, q95   (predictive quantiles), OR
    mu, sigma                     (Gaussian predictive distribution).

Usage:
  python3 scripts/calibration_eval.py predictions.csv --out-dir results/calibration
  python3 scripts/calibration_eval.py --self-test

Outputs (in --out-dir):
  calibration_report.json   per-(city, domain) coverage/width/ECE + reliability data
  calibration_table.tex     LaTeX rows for the Appendix A.11 table
  reliability_<domain>.png  reliability diagrams (one panel per city), if matplotlib available
"""

import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd

QUANTS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
QCOLS = [f"q{int(q * 100)}" for q in QUANTS]
# The nominal 90% central interval is [q5, q95]; [q10, q90] would only be the 80% interval.
INTERVAL_QUANTS = [0.05, 0.95]
INTERVAL_COLS = ["q5", "q95"]


def gaussian_quantiles(mu, sigma):
    from scipy.stats import norm

    out = {}
    for q, col in zip(QUANTS + INTERVAL_QUANTS, QCOLS + INTERVAL_COLS):
        out[col] = mu + sigma * norm.ppf(q)
    return pd.DataFrame(out)


def evaluate_group(df):
    y = df["y_true"].to_numpy()
    lo, hi = df["q5"].to_numpy(), df["q95"].to_numpy()
    coverage90 = float(np.mean((y >= lo) & (y <= hi)))
    width = float(np.mean(hi - lo))
    nominal, empirical = [], []
    for q, col in zip(QUANTS, QCOLS):
        nominal.append(q)
        empirical.append(float(np.mean(y <= df[col].to_numpy())))
    ece = float(np.mean(np.abs(np.array(empirical) - np.array(nominal))))
    return {
        "n": int(len(df)),
        "coverage90": coverage90,
        "mean_width90": width,
        "ece": ece,
        "reliability": {"nominal": nominal, "empirical": empirical},
    }


def make_plots(report, out_dir):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipping reliability diagrams")
        return
    domains = sorted({d for _, d in report})
    for dom in domains:
        cities = sorted({c for c, d in report if d == dom})
        fig, axes = plt.subplots(1, len(cities), figsize=(4 * len(cities), 3.6), squeeze=False)
        for ax, city in zip(axes[0], cities):
            r = report[(city, dom)]["reliability"]
            ax.plot([0, 1], [0, 1], "k--", lw=0.8)
            ax.plot(r["nominal"], r["empirical"], "o-", color="#1f5fa8")
            ax.set_title(f"{dom} - {city}", fontsize=10)
            ax.set_xlabel("Nominal quantile")
            ax.set_ylabel("Empirical quantile")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
        fig.tight_layout()
        path = os.path.join(out_dir, f"reliability_{dom.replace(' ', '_')}.png")
        fig.savefig(path, dpi=160)
        plt.close(fig)
        print(f"wrote {path}")


def self_test():
    """Synthetic check: a well-calibrated Gaussian forecast must yield ~90% coverage and near-zero ECE."""
    rng = np.random.default_rng(0)
    rows = []
    for city in ["NYC", "Singapore", "Nanjing"]:
        for dom in ["thermal", "pm25"]:
            mu = rng.normal(0, 1, 4000)
            sigma = np.full(4000, 1.0)
            y = mu + rng.normal(0, 1.0, 4000)  # true noise matches predicted sigma
            df = pd.DataFrame({"city": city, "domain": dom, "y_true": y, "mu": mu, "sigma": sigma})
            rows.append(df)
    df = pd.concat(rows, ignore_index=True)
    df = pd.concat([df, gaussian_quantiles(df["mu"], df["sigma"])], axis=1)
    ok = True
    for (city, dom), g in df.groupby(["city", "domain"]):
        m = evaluate_group(g)
        good = abs(m["coverage90"] - 0.9) < 0.03 and m["ece"] < 0.02
        ok &= good
        print(f"{city:10s} {dom:8s} coverage90={m['coverage90']:.3f} ece={m['ece']:.3f} {'OK' if good else 'FAIL'}")
    print("self-test", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="long-format predictions CSV")
    ap.add_argument("--out-dir", default="results/calibration")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())
    if not args.csv:
        ap.error("provide a predictions CSV or --self-test")

    df = pd.read_csv(args.csv)
    required = {"city", "domain", "y_true"}
    if not required.issubset(df.columns):
        sys.exit(f"missing columns: {required - set(df.columns)}")
    needed = set(QCOLS + INTERVAL_COLS)
    if not needed.issubset(df.columns):
        if {"mu", "sigma"}.issubset(df.columns):
            df = pd.concat([df, gaussian_quantiles(df["mu"], df["sigma"])], axis=1)
        else:
            sys.exit(f"provide either quantile columns {sorted(needed)} or mu/sigma columns")

    os.makedirs(args.out_dir, exist_ok=True)
    report = {}
    for (city, dom), g in df.groupby(["city", "domain"]):
        report[(city, dom)] = evaluate_group(g)

    json_report = {f"{c}|{d}": v for (c, d), v in report.items()}
    with open(os.path.join(args.out_dir, "calibration_report.json"), "w") as f:
        json.dump(json_report, f, indent=2)

    lines = []
    for (city, dom), m in sorted(report.items()):
        lines.append(
            f"{dom} & {city} & {m['n']} & {m['coverage90'] * 100:.1f}\\% & "
            f"{m['mean_width90']:.2f} & {m['ece']:.3f} \\\\"
        )
    with open(os.path.join(args.out_dir, "calibration_table.tex"), "w") as f:
        f.write("\n".join(lines) + "\n")

    make_plots(report, args.out_dir)
    print(f"wrote {args.out_dir}/calibration_report.json and calibration_table.tex")


if __name__ == "__main__":
    main()
