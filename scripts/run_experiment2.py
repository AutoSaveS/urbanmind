"""Experiment 2 reference pipeline: intervention-effect propagation under the
enforced record-level Track B split.

This script executes the full Experiment 2 protocol end to end:

  1. Build the Track B intervention outcome library (208 records; 3 cities x
     5 pathways) and enforce the DOI- and study-site-level partition into a
     Phase-3 fine-tuning subset and an Experiment-2 validation subset.
  2. Fine-tune each evaluation regime on the fine-tuning subset ONLY.
  3. Evaluate all three regimes (primary-response baseline, sequential
     surrogate, full coupling) on the validation subset ONLY.
  4. Apply the unified statistical protocol: CDTE with IQR normalization,
     paired cluster bootstrap over independent studies, Holm correction over
     the 15 city-pathway comparisons, and the pre-specified pass criteria.

Data status: when run without a real record library this script generates a
SYNTHETIC reference library from a generative process with known physical
couplings (canopy cooling, cooling-demand response, waste-heat feedback,
canopy deposition). The resulting numbers verify the pipeline and the split
enforcement; they are NOT the manuscript's empirical results, which require
the curated Track B library and the trained city models.

Usage: python scripts/run_experiment2.py [--steps 200] [--seed 0]
Outputs: runs/experiment2_synthetic.json, runs/trackb_record_assignment.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

import numpy as np
import torch
from torch import nn

from urbanmind.data.tracks import Record, assign_tracks, verify_disjoint, write_assignment_table
from urbanmind.eval.stats import holm_correction, paired_cluster_test, cluster_bootstrap_ci
from urbanmind.model.coupling import CouplingTensor
from urbanmind.model.world_model import GraphMessagePassing

# Domain order: 0=thermal, 1=air quality (PM2.5), 2=building energy, 3=vegetation
DOMAINS = ("thermal", "pm25", "energy", "vegetation")
PATHWAYS = [
    ("greening", "thermal"),
    ("greening", "energy"),
    ("greening", "pm25"),
    ("albedo", "thermal"),
    ("albedo", "energy"),
]
CITIES = ("city_a", "city_b", "city_c")


# --------------------------------------------------------------------------
# Synthetic Track B library with known ground-truth couplings
# --------------------------------------------------------------------------

@dataclass
class Study:
    record: Record
    city: str
    pathway: tuple[str, str]          # (intervention type, target domain)
    site_cells: np.ndarray            # cell indices of the study site
    d_canopy: float
    d_albedo: float
    observed_effect: float            # site-mean effect on the target domain
    se: float


class CityWorld:
    """Ground truth: linear coupled response with waste-heat feedback.

    dT = -aTc*dc - aTa*da + aTE*dE   (canopy/albedo cooling; waste-heat feedback)
    dE = aET*dT                      (cooling-demand response)
    dQ = -aQc*dc + aQT*dT            (canopy deposition; temperature-PM link)
    dV = dc
    """

    def __init__(self, name: str, rng: np.random.Generator, n_side: int = 12):
        self.name = name
        self.n_side = n_side
        self.n_cells = n_side * n_side
        s = lambda lo, hi: float(rng.uniform(lo, hi))  # city-specific physics
        self.aTc, self.aTa = s(2.0, 3.0), s(3.0, 4.5)
        self.aET, self.aTE = s(0.8, 1.2), s(0.25, 0.35)
        self.aQc, self.aQT = s(2.5, 3.5), s(0.6, 1.0)
        self.obs = rng.normal(size=(self.n_cells, 8)).astype(np.float32)
        # 4-neighbour grid edges
        edges = []
        for r in range(n_side):
            for c in range(n_side):
                i = r * n_side + c
                if c + 1 < n_side:
                    edges += [(i, i + 1), (i + 1, i)]
                if r + 1 < n_side:
                    edges += [(i, i + n_side), (i + n_side, i)]
        self.edge_index = torch.tensor(edges, dtype=torch.long).T

    def true_effects(self, d_canopy: float, d_albedo: float) -> dict[str, float]:
        forcing = -self.aTc * d_canopy - self.aTa * d_albedo
        dT = forcing / (1.0 - self.aTE * self.aET)
        dE = self.aET * dT
        dQ = -self.aQc * d_canopy + self.aQT * dT
        return {"thermal": dT, "energy": dE, "pm25": dQ, "vegetation": d_canopy}


def build_library(rng: np.random.Generator) -> tuple[dict[str, CityWorld], list[Study]]:
    worlds = {c: CityWorld(c, rng) for c in CITIES}
    studies: list[Study] = []
    rid = 0
    # 208 records: 14 studies per city-pathway for 13 cells of the 15 grid,
    # 13 for the remaining two (13*2 + 14*13 = 208).
    counts = {(c, p): 14 for c in CITIES for p in PATHWAYS}
    counts[(CITIES[0], PATHWAYS[0])] = 13
    counts[(CITIES[1], PATHWAYS[1])] = 13
    for city in CITIES:
        world = worlds[city]
        for pathway in PATHWAYS:
            interv, target = pathway
            for j in range(counts[(city, pathway)]):
                # Some consecutive studies share a DOI (multi-site publications)
                doi = f"10.5000/{city}.{interv}.{target}.{j // 2}"
                site_key = f"{city}:{interv}:{target}:site{j}"
                anchor = int(rng.integers(0, world.n_cells))
                site = np.unique(np.clip(anchor + rng.integers(-8, 9, size=6),
                                         0, world.n_cells - 1))
                # Real projects mix components: greening slightly changes surface
                # albedo and cool-roof programmes include some planting. The varying
                # component ratio is what makes the direct vegetation-deposition
                # pathway identifiable against the temperature-mediated route.
                if interv == "greening":
                    d_c = float(rng.uniform(0.10, 0.30))
                    d_a = float(rng.uniform(0.0, 0.06))
                else:
                    d_c = float(rng.uniform(0.0, 0.05))
                    d_a = float(rng.uniform(0.05, 0.15))
                true = world.true_effects(d_c, d_a)[target]
                noise_sd = 0.35 * abs(true) + 0.05
                if target == "pm25":  # sparse, noisy evidence for the PM pathway
                    noise_sd *= 1.3
                obs_eff = true + float(rng.normal(0, noise_sd))
                rec = Record(
                    record_id=f"B{rid:03d}", doi=doi, study_site=site_key, track="B",
                    intervention=interv, climate_tag=city, lcz_tag="",
                )
                studies.append(Study(rec, city, pathway, site, d_c, d_a, obs_eff, noise_sd))
                rid += 1
    return worlds, studies


# --------------------------------------------------------------------------
# Evaluation regimes: same architecture, different coupling masks
# --------------------------------------------------------------------------

class Exp2WorldModel(nn.Module):
    """Per-domain latent world model for Experiment 2.

    Interventions condition ONLY the directly forced domains (canopy ->
    vegetation state; albedo -> thermal via surface radiative forcing); every
    other domain can respond only through the coupling tensor, so the coupling
    mask genuinely controls cross-domain propagation.
    """

    def __init__(self, mask: torch.Tensor, dim: int = 32):
        super().__init__()
        self.dim, self.n_dom = dim, 4
        self.register_buffer("mask", mask)
        self.encoder = nn.Linear(8, self.n_dom * dim)
        self.gnn = GraphMessagePassing(dim)
        # Literature-derived prior: documented pathways (thermal<-vegetation,
        # thermal<-energy waste heat, pm25<-thermal, pm25<-vegetation deposition,
        # energy<-thermal) at moderate strength, restricted to the regime's mask.
        documented = torch.tensor([[0, 0, 1, 1],
                                   [1, 0, 0, 1],
                                   [1, 0, 0, 0],
                                   [0, 0, 0, 0.]])
        prior = (torch.eye(4) + 0.3 * documented) * mask
        self.coupling = CouplingTensor(prior=prior, sign=torch.zeros(4, 4))
        self.film_thermal = nn.Linear(1, 2 * dim)   # (d_albedo,) radiative forcing
        self.film_veg = nn.Linear(1, 2 * dim)       # (d_canopy,)
        self.decoders = nn.ModuleList([nn.Linear(dim, 1) for _ in range(4)])

    def _coupling(self) -> torch.Tensor:
        return self.coupling() * self.mask

    def rollout_effect(self, obs, edge_b, interv, horizon: int = 3) -> torch.Tensor:
        """Returns decoded fields (N, 4). interv: (N, 2) = (d_canopy, d_albedo)."""
        n = obs.size(0)
        h = self.encoder(obs).view(n, 4, self.dim)
        for _ in range(horizon):
            flat = self.gnn(h.transpose(0, 1).reshape(4 * n, self.dim), edge_b)
            h = flat.view(4, n, self.dim).transpose(0, 1)
            h = torch.einsum("md,nds->nms", self._coupling(), h)
            gt, bt = self.film_thermal(interv[:, 1:]).chunk(2, dim=-1)
            gv, bv = self.film_veg(interv[:, :1]).chunk(2, dim=-1)
            h = torch.stack(
                [(1 + gt) * h[:, 0] + bt, h[:, 1], h[:, 2], (1 + gv) * h[:, 3] + bv],
                dim=1,
            )
        return torch.cat([d(h[:, i]) for i, d in enumerate(self.decoders)], dim=-1)


MASKS = {
    # rows receive from columns; order thermal, pm25, energy, vegetation
    "primary": torch.eye(4),
    "sequential": torch.eye(4) + torch.tensor([[0, 0, 0, 1],   # thermal <- vegetation
                                               [1, 0, 0, 0],   # pm25 <- thermal
                                               [1, 0, 0, 0],   # energy <- thermal
                                               [0, 0, 0, 0.]]),
    # Full coupling is restricted to the documented pathway structure (the
    # manuscript claims prior-structured coupling, not free discovery): it adds
    # the vegetation-deposition route (pm25 <- vegetation) and the waste-heat
    # feedback (thermal <- energy) on top of the sequential chain.
    "full": torch.eye(4) + torch.tensor([[0, 0, 1, 1],
                                         [1, 0, 0, 1],
                                         [1, 0, 0, 0],
                                         [0, 0, 0, 0.]]),
}


def batched_edges(edge_index: torch.Tensor, n: int) -> torch.Tensor:
    return torch.cat([edge_index + k * n for k in range(4)], dim=1)


def predict_effect(model, world, study, base_field) -> torch.Tensor:
    """Predicted intervention effect on the study's target domain (site mean)."""
    obs = torch.from_numpy(world.obs)
    interv = torch.zeros(world.n_cells, 2)
    interv[study.site_cells, 0] = study.d_canopy
    interv[study.site_cells, 1] = study.d_albedo
    field = model.rollout_effect(obs, world.edge_b, interv)
    dom = DOMAINS.index(study.pathway[1])
    return (field - base_field)[study.site_cells, dom].mean()


def train_regime(name, worlds, ft_studies, steps, seed) -> Exp2WorldModel:
    torch.manual_seed(seed)
    model = Exp2WorldModel(MASKS[name])
    opt = torch.optim.Adam(model.parameters(), lr=5e-3)
    rng = np.random.default_rng(seed)
    scales = {d: max(np.std([s.observed_effect for s in ft_studies
                             if s.pathway[1] == d]) if any(s.pathway[1] == d for s in ft_studies)
                     else 1.0, 1e-3) for d in DOMAINS}
    for step in range(steps):
        if step % 20 == 0:
            print(f"  [{name}] step {step}/{steps}", flush=True)
        batch = rng.choice(len(ft_studies), size=min(6, len(ft_studies)), replace=False)
        opt.zero_grad()
        loss = torch.zeros(())
        base_cache = {}
        for idx in batch:
            s = ft_studies[idx]
            w = worlds[s.city]
            if s.city not in base_cache:
                base_cache[s.city] = model.rollout_effect(
                    torch.from_numpy(w.obs), w.edge_b, torch.zeros(w.n_cells, 2))
            pred = predict_effect(model, w, s, base_cache[s.city])
            loss = loss + ((pred - s.observed_effect) / scales[s.pathway[1]]) ** 2
        (loss / len(batch) + model.coupling.prior_loss()).backward()
        opt.step()
    return model


# --------------------------------------------------------------------------
# Statistical protocol
# --------------------------------------------------------------------------

def evaluate(worlds, val_studies, models) -> dict:
    """models: {regime: [seed replicates]}; predictions are seed-ensemble means
    (training seeds are optimization variability, never inference units)."""
    preds = {r: {} for r in models}
    for rname, replicates in models.items():
        with torch.no_grad():
            for model in replicates:
                base = {c: model.rollout_effect(torch.from_numpy(worlds[c].obs),
                                                worlds[c].edge_b,
                                                torch.zeros(worlds[c].n_cells, 2))
                        for c in CITIES}
                for i, s in enumerate(val_studies):
                    p = float(predict_effect(model, worlds[s.city], s, base[s.city]))
                    preds[rname][i] = preds[rname].get(i, 0.0) + p / len(replicates)

    results, reductions, pvals = {}, {}, {}
    for city in CITIES:
        for pathway in PATHWAYS:
            key = f"{city}/{pathway[0]}-{pathway[1]}"
            idx = [i for i, s in enumerate(val_studies)
                   if s.city == city and s.pathway == pathway]
            obs = np.array([val_studies[i].observed_effect for i in idx])
            q1, q3 = np.quantile(obs, [0.25, 0.75])
            iqr = max(q3 - q1, 1e-6)
            err = {r: np.abs(np.array([preds[r][i] for i in idx]) - obs) / iqr
                   for r in preds}
            cdte = {r: float(e.mean()) for r, e in err.items()}
            red = 1.0 - cdte["full"] / cdte["sequential"]
            clusters = np.arange(len(idx))  # studies are the independent units
            test = paired_cluster_test(err["sequential"], err["full"], clusters, seed=0)
            pearson = float(np.corrcoef([preds["full"][i] for i in idx], obs)[0, 1])
            results[key] = {"n_studies": len(idx), "cdte": cdte,
                            "reduction_vs_sequential": red, "pearson_r_full": pearson,
                            "p_raw": test["p"], "ci_err_diff": test["ci"]}
            reductions[key] = red
            pvals[key] = test["p"]

    holm = holm_correction(pvals)
    for key in results:
        results[key]["p_holm"] = holm[key]
        results[key]["passes_criterion"] = bool(
            results[key]["reduction_vs_sequential"] >= 0.20 and holm[key] < 0.05
            and results[key]["pearson_r_full"] >= 0.70)

    red_vals = np.array(list(reductions.values()))
    overall = cluster_bootstrap_ci(red_vals, np.arange(len(red_vals)), seed=0)
    pathway_means = {f"{p[0]}-{p[1]}": float(np.mean(
        [reductions[f"{c}/{p[0]}-{p[1]}"] for c in CITIES])) for p in PATHWAYS}
    return {
        "per_case": results,
        "mean_cdte_reduction": overall["mean"],
        "ci95": overall["ci"],
        "pass_count": sum(r["passes_criterion"] for r in results.values()),
        "n_cases": len(results),
        "pathway_mean_reductions": pathway_means,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print("== build Track B library (synthetic reference) ==")
    worlds, studies = build_library(rng)
    for w in worlds.values():
        w.edge_b = batched_edges(w.edge_index, w.n_cells)
    records = [s.record for s in studies]
    print(f"records: {len(records)}")

    print("\n== enforce record-level split (DOI + study-site disjoint) ==")
    assignment = assign_tracks(records)
    verify_disjoint(records, assignment)
    write_assignment_table(records, assignment, "runs/trackb_record_assignment.csv")
    ft = [s for s in studies if assignment[s.record.record_id] == "fine_tuning"]
    val = [s for s in studies if assignment[s.record.record_id] == "validation"]
    print(f"fine_tuning={len(ft)}, validation={len(val)}; disjointness verified")

    print("\n== Phase 3 fine-tuning (fine-tuning subset only) ==")
    n_seeds = 3
    models = {}
    for regime in ("primary", "sequential", "full"):
        print(f"training regime: {regime} ({args.steps} steps x {n_seeds} seeds)")
        models[regime] = [train_regime(regime, worlds, ft, args.steps, args.seed + k)
                          for k in range(n_seeds)]

    print("\n== Experiment 2 evaluation (validation subset only) ==")
    out = evaluate(worlds, val, models)

    print(f"\nmean CDTE reduction vs sequential: {out['mean_cdte_reduction'] * 100:.1f}% "
          f"(95% CI {out['ci95'][0] * 100:.1f}% to {out['ci95'][1] * 100:.1f}%)")
    print(f"pass count: {out['pass_count']} of {out['n_cases']}")
    print("pathway means:")
    for k, v in out["pathway_mean_reductions"].items():
        print(f"  {k}: {v * 100:.1f}%")

    out["note"] = ("Synthetic reference run verifying the enforced record-level "
                   "split and the Experiment 2 protocol; not empirical results.")
    with open("runs/experiment2_synthetic.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote runs/experiment2_synthetic.json and runs/trackb_record_assignment.csv")


if __name__ == "__main__":
    main()
