"""Physical constraint projection and sub-grid downscaling with closure guarantees.

The projection is an explicit optimization problem (objective, bounds, weights,
tolerances, solver, convergence criteria) as documented in manuscript Appendix A.10.
Residual distributions before and after projection quantify how strongly grounding
modifies the free rollout.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize


@dataclass
class LinearConstraint:
    """Soft linear constraint a . x = b with retrieval-confidence weight."""

    a: np.ndarray
    b: float
    weight: float

    def residual(self, x: np.ndarray) -> float:
        return float(self.a @ x - self.b)


class ConstraintProjector:
    """Projects a rollout state onto the physically feasible region.

    minimize   ||x - x_free||^2 + sum_k w_k * (a_k.x - b_k)^2
    subject to lower <= x <= upper

    Solved with L-BFGS-B; convergence tolerance and iteration cap are explicit so
    runs are reproducible.
    """

    def __init__(self, tol: float = 1e-8, max_iter: int = 200):
        self.tol = tol
        self.max_iter = max_iter

    def project(
        self,
        x_free: np.ndarray,
        constraints: list[LinearConstraint],
        lower: np.ndarray | None = None,
        upper: np.ndarray | None = None,
    ) -> dict:
        def objective(x):
            fidelity = np.sum((x - x_free) ** 2)
            penalty = sum(c.weight * c.residual(x) ** 2 for c in constraints)
            return fidelity + penalty

        bounds = None
        if lower is not None or upper is not None:
            lo = lower if lower is not None else np.full_like(x_free, -np.inf)
            hi = upper if upper is not None else np.full_like(x_free, np.inf)
            bounds = list(zip(lo, hi))

        result = optimize.minimize(
            objective, x_free, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": self.max_iter, "ftol": self.tol},
        )
        return {
            "x": result.x,
            "converged": bool(result.success),
            "n_iter": int(result.nit),
            "residuals_before": [c.residual(x_free) for c in constraints],
            "residuals_after": [c.residual(result.x) for c in constraints],
        }


def subgrid_downscale(
    parent_value: float,
    corrections: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    """CFD-calibrated sub-grid correction with parent-cell closure.

    The weighted mean of the sub-grid deviations is explicitly removed, so the
    weighted average of returned sub-cells equals the 500 m parent value exactly
    (the conservation condition asserted "by construction" in Eq. 10). Outputs are
    illustrative downscaling for design communication, not validated canyon-scale
    accuracy.
    """
    weights = weights / weights.sum()
    centered = corrections - np.sum(weights * corrections)
    sub = parent_value + centered
    closure_error = abs(float(np.sum(weights * sub) - parent_value))
    assert closure_error < 1e-10, f"closure violated: {closure_error}"
    return sub
