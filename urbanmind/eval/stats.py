"""Unified statistical protocol (manuscript Section 4.5).

One pre-specified protocol governs all analyses:

- Resampling/testing units are genuinely independent units: spatial blocks for
  grid-level comparisons, monitoring stations for station-holdout metrics, and
  intervention studies for Experiment 2. Training seeds are optimization
  variability only and are never used as inference units.
- All pairwise comparisons use paired cluster bootstrap (10,000 resamples) with
  Cohen's d effect sizes and Holm correction within each pre-declared test family.
- Every reported comparison includes sample size, effect size, and 95% CI.
- Cross-domain averaging of scale-dependent errors normalizes each domain by the
  IQR of its test-set observations (see `iqr_normalize`).
"""

import numpy as np

N_RESAMPLES = 10_000


def _cluster_means(values: np.ndarray, clusters: np.ndarray) -> np.ndarray:
    """Mean of `values` within each cluster (cluster ids need not be consecutive)."""
    unique, inverse = np.unique(clusters, return_inverse=True)
    sums = np.zeros(len(unique))
    counts = np.zeros(len(unique))
    np.add.at(sums, inverse, values)
    np.add.at(counts, inverse, 1)
    return sums / counts


def cluster_bootstrap_ci(
    values: np.ndarray,
    clusters: np.ndarray,
    n_resamples: int = N_RESAMPLES,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict:
    """Percentile CI for the mean, resampling clusters (not observations)."""
    rng = np.random.default_rng(seed)
    cm = _cluster_means(values, clusters)
    k = len(cm)
    idx = rng.integers(0, k, size=(n_resamples, k))
    boot = cm[idx].mean(axis=1)
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return {"mean": float(cm.mean()), "ci": (float(lo), float(hi)), "n_clusters": k}


def cohens_d(diff_cluster_means: np.ndarray) -> float:
    sd = diff_cluster_means.std(ddof=1)
    return float(diff_cluster_means.mean() / sd) if sd > 0 else float("inf")


def paired_cluster_test(
    a: np.ndarray,
    b: np.ndarray,
    clusters: np.ndarray,
    n_resamples: int = N_RESAMPLES,
    seed: int = 0,
) -> dict:
    """Paired comparison of two conditions measured on the same units.

    Returns the mean difference, bootstrap 95% CI, two-sided bootstrap p-value,
    Cohen's d over cluster means, and the number of independent units.
    """
    rng = np.random.default_rng(seed)
    diff = _cluster_means(a - b, clusters)
    k = len(diff)
    idx = rng.integers(0, k, size=(n_resamples, k))
    boot = diff[idx].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    # Two-sided p: shift distribution to the null and count exceedances.
    centered = boot - diff.mean()
    p = float(np.mean(np.abs(centered) >= abs(diff.mean())))
    return {
        "mean_diff": float(diff.mean()),
        "ci": (float(lo), float(hi)),
        "p": max(p, 1.0 / n_resamples),
        "cohens_d": cohens_d(diff),
        "n_clusters": k,
    }


def holm_correction(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjustment within one pre-declared test family."""
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running_max = 0.0
    for rank, (name, p) in enumerate(items):
        adj = min(1.0, (m - rank) * p)
        running_max = max(running_max, adj)
        adjusted[name] = running_max
    return adjusted


def iqr_normalize(errors: np.ndarray, observations: np.ndarray) -> np.ndarray:
    """Normalize scale-dependent errors by the IQR of test-set observations."""
    q1, q3 = np.quantile(observations, [0.25, 0.75])
    iqr = q3 - q1
    if iqr <= 0:
        raise ValueError("Degenerate IQR; cannot normalize")
    return errors / iqr
