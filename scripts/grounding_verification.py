#!/usr/bin/env python3
"""Verification suite for the released KRCG grounding implementation (R1.4).

Two properties of urbanmind/model/grounding.py are verified so the manuscript
can report them as reproducible facts of the released implementation:

  1. Parent-cell closure of the sub-grid downscaling (Eq. 10): the weighted
     mean of the sub-grid values must equal the 500 m parent value exactly.
     Verified over N random cases; the maximum absolute closure error is
     reported (machine precision, ~1e-15).

  2. Constraint projection (Eqs. 8-9 -> Appendix): residual distributions
     before and after projection over N random verification scenarios
     (energy-balance style soft linear constraints with retrieval-confidence
     weights, box bounds on the state). Reports median/p90 absolute residual
     before and after, the median reduction, and the convergence rate of the
     L-BFGS-B solver (ftol 1e-8, max 200 iterations).

These are properties of the released pipeline, not statistics of the trained
system's city runs.
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from urbanmind.model.grounding import (ConstraintProjector, LinearConstraint,
                                       subgrid_downscale)

SEED = 20260812
N_CASES = 1000
OUT = Path(__file__).resolve().parents[1] / "data" / "grounding_verification.json"


def verify_closure(rng):
    worst = 0.0
    for _ in range(N_CASES):
        n_sub = rng.integers(4, 26)
        parent = float(rng.normal(20, 10))
        corrections = rng.normal(0, 3, n_sub)
        weights = rng.uniform(0.1, 1.0, n_sub)
        sub = subgrid_downscale(parent, corrections, weights)
        w = weights / weights.sum()
        worst = max(worst, abs(float(np.sum(w * sub) - parent)))
    return worst


def verify_projection(rng):
    projector = ConstraintProjector()  # released defaults: ftol 1e-8, 200 iter
    before, after, iters, converged = [], [], [], 0
    for _ in range(N_CASES):
        dim = int(rng.integers(4, 13))
        x_free = rng.normal(0, 1, dim)
        constraints = []
        for _ in range(int(rng.integers(2, 6))):
            a = rng.normal(0, 1, dim)
            # target offset so the free state genuinely violates the constraint
            b = float(a @ x_free + rng.normal(0, 1.5))
            constraints.append(LinearConstraint(a=a, b=b,
                                                weight=float(rng.uniform(0.5, 5.0))))
        lower = x_free - 3.0
        upper = x_free + 3.0
        res = projector.project(x_free, constraints, lower, upper)
        before += [abs(r) for r in res["residuals_before"]]
        after += [abs(r) for r in res["residuals_after"]]
        iters.append(res["n_iter"])
        converged += int(res["converged"])
    before, after = np.array(before), np.array(after)
    return {
        "n_scenarios": N_CASES,
        "n_constraints": int(len(before)),
        "median_abs_residual_before": float(np.median(before)),
        "median_abs_residual_after": float(np.median(after)),
        "p90_abs_residual_before": float(np.percentile(before, 90)),
        "p90_abs_residual_after": float(np.percentile(after, 90)),
        "median_reduction_pct": float(100 * (1 - np.median(after / np.maximum(before, 1e-12)))),
        "convergence_rate": converged / N_CASES,
        "median_iterations": float(np.median(iters)),
        "max_iterations": int(max(iters)),
    }


def main():
    rng = np.random.default_rng(SEED)
    closure = verify_closure(rng)
    proj = verify_projection(rng)
    report = {"seed": SEED,
              "max_closure_error": closure,
              "projection": proj}
    OUT.write_text(json.dumps(report, indent=2))
    print(f"closure: max |weighted mean - parent| over {N_CASES} cases = {closure:.2e}")
    p = proj
    print(f"projection ({p['n_scenarios']} scenarios, {p['n_constraints']} constraints):")
    print(f"  |residual| median {p['median_abs_residual_before']:.3f} -> "
          f"{p['median_abs_residual_after']:.3f}  "
          f"(median reduction {p['median_reduction_pct']:.1f}%)")
    print(f"  p90 {p['p90_abs_residual_before']:.3f} -> {p['p90_abs_residual_after']:.3f}")
    print(f"  convergence {100*p['convergence_rate']:.1f}%, median iterations "
          f"{p['median_iterations']:.0f} (max {p['max_iterations']})")
    print(f"report: {OUT}")


if __name__ == "__main__":
    main()
