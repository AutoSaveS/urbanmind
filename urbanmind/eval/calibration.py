"""Uncertainty calibration evaluation (manuscript Appendix A.11).

Reports empirical coverage of nominal prediction intervals, mean interval width,
expected calibration error over the quantile set {0.1, ..., 0.9}, and the points
needed for reliability diagrams.
"""

import numpy as np
from scipy import stats as sps

QUANTILES = np.arange(0.1, 0.91, 0.1)


def calibration_report(
    mean: np.ndarray, sigma: np.ndarray, target: np.ndarray, nominal: float = 0.9
) -> dict:
    z = sps.norm.ppf(0.5 + nominal / 2)
    lower, upper = mean - z * sigma, mean + z * sigma
    covered = (target >= lower) & (target <= upper)

    # Reliability curve: nominal vs empirical quantile coverage.
    standardized = (target - mean) / sigma
    reliability = []
    for q in QUANTILES:
        empirical = float(np.mean(standardized <= sps.norm.ppf(q)))
        reliability.append({"nominal": float(q), "empirical": empirical})
    ece = float(np.mean([abs(r["nominal"] - r["empirical"]) for r in reliability]))

    return {
        "nominal_coverage": nominal,
        "empirical_coverage": float(covered.mean()),
        "mean_interval_width": float((upper - lower).mean()),
        "ece": ece,
        "reliability": reliability,
        "n": int(target.size),
    }
