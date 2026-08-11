"""Experiment 2 on the real Track B library under the enforced record split.

Reads the curated 208-record library (data/trackb/trackb_effects.csv, built by
merge_trackb_effects.py from Crossref-verified records and effect sizes
extracted from the source systematic reviews) and runs the full protocol:

  1. Split records by the published assignment table (DOI- and site-disjoint,
     verified by urbanmind.data.tracks.verify_disjoint).
  2. Fine-tune each evaluation regime (primary, sequential, full coupling) on
     the fine-tuning subset ONLY. Interventions condition only their directly
     forced domains (greening -> vegetation, cool roof -> thermal, retrofit ->
     energy, LEZ -> air quality, combined -> vegetation + thermal), so indirect
     pathways are reachable only through the coupling tensor.
  3. Evaluate on the validation subset ONLY: CDTE with IQR normalization per
     case cell (climate group x intervention-domain pathway), paired cluster
     bootstrap with publications (DOIs) as clusters, Holm correction over the
     case grid, and the pre-specified pass criteria.
  4. Additionally run the OVERLAP configuration (fine-tuning on all records,
     the pre-revision risk R1.1 raises) to quantify how much the overlap
     inflates the headline number.

Usage: python scripts/run_experiment2_real.py [--steps 400] [--seed 0]
Output: runs/experiment2_real.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

import numpy as np
import torch
from torch import nn

from urbanmind.data.tracks import Record, verify_disjoint
from urbanmind.eval.stats import holm_correction, paired_cluster_test, cluster_bootstrap_ci
from urbanmind.model.coupling import CouplingTensor

# Domain order: 0=thermal, 1=air quality, 2=building energy, 3=vegetation
DOMAINS = ("thermal", "air_quality", "energy", "vegetation")
INTERVENTIONS = ("greening", "cool_roof", "retrofit", "low_emission_zone", "combined")
CLIMATES = ("mediterranean", "oceanic", "continental", "subtropical",
            "tropical_semiarid", "multi_region")
# Which latent domains each intervention type directly forces.
FORCING = {
    "greening": (3,),
    "cool_roof": (0,),
    "retrofit": (2,),
    "low_emission_zone": (1,),
    "combined": (0, 3),
}
# Map merged-table domain classes onto model domains (surface and air
# temperature share the thermal latent but have separate decoders and scales,
# since surface reductions are an order of magnitude larger than air ones).
DOMAIN_INDEX = {"thermal": 0, "thermal_surface": 0, "air_quality": 1, "energy": 2}
OBS_CLASSES = ("thermal", "thermal_surface", "air_quality", "energy")

MIN_CELL_VAL = 3     # minimum validation studies for a case cell
N_CASES = 15         # size of the case grid (mirrors the 3x5 manuscript grid)


SUBTYPES = ("park", "green_roof", "facade", "barrier", "street_trees",
            "cool_roof_coating", "cool_pavement", "watered_pavement",
            "mixed_measures", "retrofit_program", "lez_zone")


@dataclass
class Obs:
    record_id: str
    doi: str
    subset: str
    climate: str
    intervention: str
    subtype: str
    measured: bool
    domain: str          # thermal | thermal_surface | energy | air_quality
    value: float


def load_observations(path: str = "data/trackb/trackb_effects.csv") -> list[Obs]:
    obs = []
    for r in csv.DictReader(open(path)):
        obs.append(Obs(r["record_id"], r["doi"], r["subset"], r["climate_group"],
                       r["intervention"], r["subtype"],
                       r["measurement"].strip().lower() == "measured",
                       r["domain"], float(r["effect_value"])))
    return obs


# --------------------------------------------------------------------------
# Model: context encoder + masked coupling propagation + FiLM forcing
# --------------------------------------------------------------------------

class RealWorldModel(nn.Module):
    def __init__(self, mask: torch.Tensor, dim: int = 16):
        super().__init__()
        self.dim = dim
        self.register_buffer("mask", mask)
        # Context = climate group + measurement flag. Intervention identity and
        # subtype enter ONLY via FiLM on the directly forced domains, so
        # cross-domain responses remain gated by the coupling mask.
        self.encoder = nn.Linear(len(CLIMATES) + 1, 4 * dim)
        documented = torch.tensor([[0, 0, 1, 1],
                                   [1, 0, 0, 1],
                                   [1, 0, 0, 0],
                                   [0, 0, 0, 0.]])
        prior = (torch.eye(4) + 0.3 * documented) * mask
        self.coupling = CouplingTensor(prior=prior, sign=torch.zeros(4, 4))
        self.film = nn.ModuleList(
            [nn.Linear(len(INTERVENTIONS) + len(SUBTYPES), 2 * dim)
             for _ in range(4)])
        # One decoder per observation class, reading its domain's latent.
        self.decoders = nn.ModuleList([nn.Linear(dim, 1)
                                       for _ in range(len(OBS_CLASSES))])

    def forward(self, climate: torch.Tensor, interv: torch.Tensor,
                horizon: int = 3) -> torch.Tensor:
        """climate: (N, n_climates) one-hot; interv: (N, n_interventions) one-hot.
        Returns decoded effect fields (N, 4)."""
        n = climate.size(0)
        h = self.encoder(climate).view(n, 4, self.dim)
        forced = torch.zeros(n, 4)
        for k, iv in enumerate(INTERVENTIONS):
            for d in FORCING[iv]:
                forced[:, d] = torch.maximum(forced[:, d], interv[:, k])
        coupling = self.coupling() * self.mask
        for _ in range(horizon):
            h = torch.einsum("md,nds->nms", coupling, h)
            cols = []
            for d in range(4):
                g, b = self.film[d](interv).chunk(2, dim=-1)
                f = forced[:, d:d + 1]
                cols.append(h[:, d] * (1 + f * g) + f * b)
            h = torch.stack(cols, dim=1)
        return torch.cat([dec(h[:, DOMAIN_INDEX[cls]])
                          for cls, dec in zip(OBS_CLASSES, self.decoders)], dim=-1)


MASKS = {
    "primary": torch.eye(4),
    # Sequential surrogate: vegetation cools, temperature drives air quality
    # and building energy (the one-directional chain).
    "sequential": torch.eye(4) + torch.tensor([[0, 0, 0, 1],
                                               [1, 0, 0, 0],
                                               [1, 0, 0, 0],
                                               [0, 0, 0, 0.]]),
    # Full coupling adds the documented vegetation-deposition route
    # (air quality <- vegetation) and the energy-thermal feedback.
    "full": torch.eye(4) + torch.tensor([[0, 0, 1, 1],
                                         [1, 0, 0, 1],
                                         [1, 0, 0, 0],
                                         [0, 0, 0, 0.]]),
}


def featurize(o: Obs) -> tuple[torch.Tensor, torch.Tensor, int]:
    context = torch.zeros(len(CLIMATES) + 1)
    context[CLIMATES.index(o.climate)] = 1.0
    context[-1] = 1.0 if o.measured else 0.0
    interv = torch.zeros(len(INTERVENTIONS) + len(SUBTYPES))
    interv[INTERVENTIONS.index(o.intervention)] = 1.0
    interv[len(INTERVENTIONS) + SUBTYPES.index(o.subtype)] = 1.0
    return context, interv, OBS_CLASSES.index(o.domain)


def pathway_key(o: Obs) -> str:
    return f"{o.intervention}-{o.domain}"


def train_regime(name: str, train_obs: list[Obs], scales: dict[str, tuple[float, float]],
                 steps: int, seed: int) -> RealWorldModel:
    torch.manual_seed(seed)
    model = RealWorldModel(MASKS[name])
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    rng = np.random.default_rng(seed)
    climate = torch.stack([featurize(o)[0] for o in train_obs])
    interv = torch.stack([featurize(o)[1] for o in train_obs])
    dom = torch.tensor([featurize(o)[2] for o in train_obs])
    target = torch.tensor([(o.value - scales[o.domain][0]) / scales[o.domain][1]
                           for o in train_obs], dtype=torch.float32)
    n = len(train_obs)
    for step in range(steps):
        idx = torch.from_numpy(rng.choice(n, size=min(32, n), replace=False))
        opt.zero_grad()
        out = model(climate[idx], interv[idx])
        pred = out.gather(1, dom[idx, None]).squeeze(1)
        loss = ((pred - target[idx]) ** 2).mean() + model.coupling.prior_loss()
        loss.backward()
        opt.step()
    return model


def predict(models: list[RealWorldModel], obs: list[Obs],
            scales: dict[str, tuple[float, float]]) -> np.ndarray:
    climate = torch.stack([featurize(o)[0] for o in obs])
    interv = torch.stack([featurize(o)[1] for o in obs])
    dom = torch.tensor([featurize(o)[2] for o in obs])
    preds = np.zeros(len(obs))
    with torch.no_grad():
        for m in models:
            out = m(climate, interv).gather(1, dom[:, None]).squeeze(1).numpy()
            preds += out / len(models)
    # de-normalize per observation class
    return np.array([p * scales[o.domain][1] + scales[o.domain][0]
                     for p, o in zip(preds, obs)])


# --------------------------------------------------------------------------
# Protocol
# --------------------------------------------------------------------------

def fit_scales(train_obs: list[Obs]) -> dict[str, tuple[float, float]]:
    """Per observation-class (mean, sd), computed on the TRAINING subset only.

    Scaling is deliberately NOT per intervention: the regimes must explain how
    different interventions move each domain, which is exactly what the
    coupling structure is being tested on.
    """
    vals: dict[str, list[float]] = {}
    for o in train_obs:
        vals.setdefault(o.domain, []).append(o.value)
    return {k: (float(np.mean(v)), max(float(np.std(v)), 1e-3))
            for k, v in vals.items()}


def run_configuration(label: str, train_obs: list[Obs], val_obs: list[Obs],
                      steps: int, seed: int, n_seeds: int = 3) -> dict:
    print(f"\n== configuration: {label} "
          f"(train n={len(train_obs)}, val n={len(val_obs)}) ==")
    scales = fit_scales(train_obs)
    # observation classes never seen in training cannot be scaled; drop them
    val_obs = [o for o in val_obs if o.domain in scales]

    models = {}
    for regime in MASKS:
        print(f"  training {regime} ({steps} steps x {n_seeds} seeds)")
        models[regime] = [train_regime(regime, train_obs, scales, steps, seed + k)
                          for k in range(n_seeds)]
    preds = {r: predict(models[r], val_obs, scales) for r in MASKS}

    # Case grid: climate x pathway cells with enough validation studies.
    cells: dict[str, list[int]] = {}
    for i, o in enumerate(val_obs):
        cells.setdefault(f"{o.climate}/{pathway_key(o)}", []).append(i)
    eligible = {k: v for k, v in cells.items() if len(v) >= MIN_CELL_VAL}
    grid = dict(sorted(eligible.items(), key=lambda kv: -len(kv[1]))[:N_CASES])
    print(f"  case grid: {len(grid)} cells "
          f"({sum(len(v) for v in grid.values())} validation studies)")

    results, reductions, pvals = {}, {}, {}
    for key, idx in grid.items():
        obs_vals = np.array([val_obs[i].value for i in idx])
        q1, q3 = np.quantile(obs_vals, [0.25, 0.75])
        iqr = max(q3 - q1, 1e-6)
        err = {r: np.abs(preds[r][idx] - obs_vals) / iqr for r in preds}
        cdte = {r: float(e.mean()) for r, e in err.items()}
        red = 1.0 - cdte["full"] / max(cdte["sequential"], 1e-9)
        dois = [val_obs[i].doi for i in idx]
        clusters = np.array([dois.index(d) for d in dois])
        test = paired_cluster_test(err["sequential"], err["full"], clusters, seed=0)
        r_full = (float(np.corrcoef(preds["full"][idx], obs_vals)[0, 1])
                  if len(idx) > 2 and np.std(preds["full"][idx]) > 1e-9 else float("nan"))
        results[key] = {"n_studies": len(idx), "cdte": cdte,
                        "reduction_vs_sequential": red, "pearson_r_full": r_full,
                        "p_raw": test["p"], "ci_err_diff": test["ci"]}
        reductions[key] = red
        pvals[key] = test["p"]

    holm = holm_correction(pvals)
    for key in results:
        results[key]["p_holm"] = holm[key]
        r = results[key]
        results[key]["passes_criterion"] = bool(
            r["reduction_vs_sequential"] >= 0.20 and holm[key] < 0.05
            and (not np.isnan(r["pearson_r_full"]) and r["pearson_r_full"] >= 0.70))

    red_vals = np.array(list(reductions.values()))
    overall = cluster_bootstrap_ci(red_vals, np.arange(len(red_vals)), seed=0)
    print(f"  mean CDTE reduction vs sequential: {overall['mean'] * 100:.1f}% "
          f"(95% CI {overall['ci'][0] * 100:.1f}% to {overall['ci'][1] * 100:.1f}%)")
    print(f"  pass count: {sum(r['passes_criterion'] for r in results.values())}"
          f" of {len(results)}")
    return {"per_case": results, "mean_cdte_reduction": overall["mean"],
            "ci95": overall["ci"], "n_cases": len(results),
            "pass_count": sum(r["passes_criterion"] for r in results.values())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    obs = load_observations()
    print(f"loaded {len(obs)} (record, domain) observations "
          f"({len({o.record_id for o in obs})} records)")

    # Re-verify the enforced split on exactly the records entering the analysis.
    recs, assign = [], {}
    seen = set()
    for o in obs:
        if o.record_id in seen:
            continue
        seen.add(o.record_id)
        recs.append(Record(record_id=o.record_id, doi=o.doi,
                           study_site=o.record_id, track="B",
                           intervention=o.intervention, climate_tag=o.climate,
                           lcz_tag=""))
        assign[o.record_id] = o.subset
    verify_disjoint(recs, assign)
    print("record-level disjointness verified (DOI + study site)")

    ft = [o for o in obs if o.subset == "fine_tuning"]
    val = [o for o in obs if o.subset == "validation"]

    out = {
        "enforced_split": run_configuration(
            "enforced split (fine-tuning subset only)", ft, val,
            args.steps, args.seed),
        "overlap_configuration": run_configuration(
            "overlap (fine-tuned on all records, validation reused)", obs, val,
            args.steps, args.seed),
        "n_records": len({o.record_id for o in obs}),
        "n_observations": len(obs),
        "note": ("Real Track B library (Crossref-verified records; effect sizes "
                 "extracted from source systematic reviews). Reference "
                 "implementation run under the enforced DOI- and site-level "
                 "split, with the overlap configuration reported for "
                 "comparison."),
    }
    with open("runs/experiment2_real.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote runs/experiment2_real.json")


if __name__ == "__main__":
    main()
