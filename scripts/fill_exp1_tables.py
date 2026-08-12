#!/usr/bin/env python3
"""Turn a real exp1_blocked_report.json (produced by exp1_blocked_inference.py
on the per-cell test predictions) into the LaTeX fragments that complete the
manuscript and response letter (R1.5, R1.6):

  - appendix_a3_task_rows.tex : 12 rows with R^2 [95% block CI], RMSE, MAE,
    paired Delta R^2 [95% CI] and Holm-adjusted p, under spatial blocking;
  - blocked_summary.txt       : macro-average CI (spatial and temporal),
    per-task Holm outcomes, and the temporal-vs-spatial comparison needed for
    the R1.6 placeholder.

Usage:
  python3 scripts/fill_exp1_tables.py path/to/exp1_blocked_report.json

The script refuses obvious demo output (synthetic macro effect ~0.16) unless
--allow-demo is given, so synthetic numbers cannot be pasted into the paper by
accident.
"""

import argparse
import json
from pathlib import Path

DOMAIN_LABELS = {
    "temperature": "Thermal / UHI", "thermal": "Thermal / UHI",
    "energy": "Building energy", "pm25": "Air quality PM$_{2.5}$",
    "air": "Air quality PM$_{2.5}$", "vegetation": "Vegetation NDVI",
    "veg": "Vegetation NDVI",
}


def fmt_ci(ci):
    return f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--allow-demo", action="store_true")
    args = ap.parse_args()
    rep = json.loads(Path(args.report).read_text())

    macro = rep["spatial"]["macro_delta_r2"]
    if abs(macro) > 0.05 and not args.allow_demo:
        raise SystemExit(
            f"macro delta R^2 = {macro:+.3f} looks like the synthetic demo "
            f"(expected ~+0.013 for the real benchmark); pass --allow-demo "
            f"only if this is intentional")

    outdir = Path(args.report).parent
    rows = []
    for key, t in rep["spatial"]["tasks"].items():
        city, domain = key.split("/")
        um = t["urbanmind"]
        label = DOMAIN_LABELS.get(domain.lower(), domain)
        holm = t["p_holm"]
        sig = "$p<0.01$" if holm < 0.01 else ("$p<0.05$" if holm < 0.05
                                              else "n.s.")
        rows.append(
            f"{city} & {label} & {um['r2']:.3f} {fmt_ci(um['r2_ci'])} & "
            f"{um['rmse']:.3g} & {um['mae']:.3g} & "
            f"{t['delta_r2']:+.3f} {fmt_ci(t['delta_r2_ci95'])} & {sig} \\\\")
    (outdir / "appendix_a3_task_rows.tex").write_text("\n".join(rows) + "\n")

    s, tp = rep["spatial"], rep["temporal"]
    lines = [
        "== macro-average Delta R^2 ==",
        f"spatial : {s['macro_delta_r2']:+.4f}  95% CI {fmt_ci(s['macro_delta_r2_ci95'])}  p={s['macro_p_boot']:.4f}",
        f"temporal: {tp['macro_delta_r2']:+.4f}  95% CI {fmt_ci(tp['macro_delta_r2_ci95'])}  p={tp['macro_p_boot']:.4f}",
        "",
        "== per-task Holm outcomes (spatial blocks) ==",
    ]
    n_sig = 0
    for key, t in s["tasks"].items():
        flag = "SIG" if t["p_holm"] < 0.05 else "n.s."
        n_sig += t["p_holm"] < 0.05
        lines.append(f"{key:24s} dR2 {t['delta_r2']:+.3f} "
                     f"{fmt_ci(t['delta_r2_ci95'])}  Holm p {t['p_holm']:.4f} {flag}")
    lines.append(f"\nsignificant after Holm: {n_sig}/{len(s['tasks'])}")
    (outdir / "blocked_summary.txt").write_text("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"\nwrote: {outdir / 'appendix_a3_task_rows.tex'}")
    print(f"wrote: {outdir / 'blocked_summary.txt'}")


if __name__ == "__main__":
    main()
