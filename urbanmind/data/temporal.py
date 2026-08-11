"""Temporal harmonization with a full provenance audit (manuscript Appendix A.9).

Daily, monthly, and intermittent observations are converted into model-ready
sequences. Every produced value carries a provenance flag so the audit table --
proportions of measured / interpolated / rule-based downscaled / missing values per
variable and city -- can be generated mechanically rather than asserted.

Scope note mirrored from the manuscript: the formally evaluated prediction targets
are the *daily* 500 m fields; hourly states are an internal computational
representation and are never claimed as validated outputs.
"""

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np


class Provenance(IntEnum):
    MISSING = 0
    MEASURED = 1
    INTERPOLATED = 2
    RULE_DOWNSCALED = 3


# Uncertainty inflation attached at each harmonization stage, expressed as a
# multiplier on the observation-level standard deviation. Propagates into the
# aleatoric term of the training loss.
UNCERTAINTY_INFLATION = {
    Provenance.MEASURED: 1.0,
    Provenance.INTERPOLATED: 1.5,
    Provenance.RULE_DOWNSCALED: 2.0,
    Provenance.MISSING: np.inf,
}


@dataclass
class HarmonizedSeries:
    values: np.ndarray        # (T,) float, NaN where missing
    provenance: np.ndarray    # (T,) Provenance
    sigma_scale: np.ndarray   # (T,) uncertainty inflation applied


@dataclass
class HarmonizationAudit:
    """Accumulates provenance counts per (variable, city)."""

    counts: dict = field(default_factory=dict)

    def add(self, city: str, variable: str, provenance: np.ndarray) -> None:
        key = (city, variable)
        bins = np.bincount(provenance.astype(int), minlength=4)
        self.counts[key] = self.counts.get(key, np.zeros(4, dtype=int)) + bins

    def table(self) -> list[dict]:
        """Rows for the supplementary audit table (proportions sum to 1)."""
        rows = []
        for (city, variable), bins in sorted(self.counts.items()):
            total = bins.sum()
            rows.append({
                "city": city,
                "variable": variable,
                "measured": bins[Provenance.MEASURED] / total,
                "interpolated": bins[Provenance.INTERPOLATED] / total,
                "rule_downscaled": bins[Provenance.RULE_DOWNSCALED] / total,
                "missing": bins[Provenance.MISSING] / total,
                "n": int(total),
            })
        return rows


def harmonize_series(
    timestamps: np.ndarray,
    values: np.ndarray,
    target_length: int,
    native_step: int,
    max_gap: int = 3,
) -> HarmonizedSeries:
    """Convert an observed series to a model-ready daily sequence.

    timestamps: integer day indices where observations exist (sorted).
    values: observed values at those days.
    target_length: length of the model-ready daily sequence.
    native_step: native sampling interval in days (1 = daily, 30 = monthly, ...).
    max_gap: interpolate across gaps up to this many native steps; beyond that,
        values are rule-downscaled if native_step > 1, else left missing.
    """
    out = np.full(target_length, np.nan)
    prov = np.full(target_length, Provenance.MISSING, dtype=int)

    out[timestamps] = values
    prov[timestamps] = Provenance.MEASURED

    obs_idx = np.flatnonzero(prov == Provenance.MEASURED)
    for left, right in zip(obs_idx[:-1], obs_idx[1:]):
        gap = right - left
        if gap <= 1:
            continue
        if native_step > 1 and gap <= max_gap * native_step:
            # Coarse sources (e.g. monthly energy totals): values inside the native
            # window are not observed at all, so they are spread by rule (constant
            # allocation) rather than treated as interpolation between daily points.
            t = np.arange(left + 1, right)
            out[t] = out[left]
            prov[t] = Provenance.RULE_DOWNSCALED
        elif native_step == 1 and gap <= max_gap:
            # Daily sources: linear interpolation across short observation gaps.
            t = np.arange(left + 1, right)
            out[t] = np.interp(t, [left, right], [out[left], out[right]])
            prov[t] = Provenance.INTERPOLATED

    sigma = np.array([UNCERTAINTY_INFLATION[Provenance(p)] for p in prov])
    return HarmonizedSeries(values=out, provenance=prov, sigma_scale=sigma)
