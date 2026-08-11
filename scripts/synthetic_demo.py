"""End-to-end smoke run on synthetic data.

Exercises the full chain -- grid, harmonization audit, world-model rollout, KRCG
retrieval, constraint projection, downscaling closure, uncertainty decomposition,
statistical protocol, calibration report, runtime logging -- without any external
data. This validates the plumbing, not scientific claims.

Usage: python scripts/synthetic_demo.py
"""

import sys

sys.path.insert(0, ".")

import numpy as np
import torch

from urbanmind.data.grid import CityGrid, make_spatial_blocks
from urbanmind.data.temporal import HarmonizationAudit, harmonize_series
from urbanmind.data.tracks import Record, assign_tracks, verify_disjoint
from urbanmind.eval.calibration import calibration_report
from urbanmind.eval.stats import holm_correction, paired_cluster_test
from urbanmind.model.grounding import ConstraintProjector, LinearConstraint, subgrid_downscale
from urbanmind.model.krcg import KnowledgeEntry, KnowledgeLibrary, KRCGRetriever
from urbanmind.model.uncertainty import decompose_uncertainty
from urbanmind.model.world_model import GraphWorldModel
from urbanmind.runtime.benchmark import RuntimeBenchmark

rng = np.random.default_rng(0)
torch.manual_seed(0)

print("== grid & spatial blocks ==")
grid = CityGrid("synthville", n_rows=20, n_cols=20)
blocks = make_spatial_blocks(grid, block_cells=5)
print(f"cells={grid.n_valid}, blocks={blocks.max() + 1}")

print("\n== temporal harmonization audit ==")
audit = HarmonizationAudit()
monthly_days = np.arange(0, 360, 30)
series = harmonize_series(monthly_days, rng.normal(size=len(monthly_days)),
                          target_length=365, native_step=30)
audit.add("synthville", "building_energy", series.provenance)
for row in audit.table():
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()})

print("\n== track assignment (record-level split) ==")
records = [
    Record(f"B{i:03d}", doi=f"10.1000/study{i // 2}", study_site=f"site{i % 5}", track="B")
    for i in range(20)
]
assignment = assign_tracks(records)
verify_disjoint(records, assignment)
print("disjointness verified:",
      {s: sum(1 for v in assignment.values() if v == s) for s in set(assignment.values())})

print("\n== world model rollout ==")
n_cells, obs_dim = 100, 8
edge_index = torch.randint(0, n_cells, (2, 400))
model = GraphWorldModel(obs_dim=obs_dim)
obs = torch.randn(n_cells, obs_dim)
intervention = torch.tensor([0.3, 0.0, 0.0, 0.0]).expand(n_cells, -1)
means, sigmas = model.rollout(obs, edge_index, intervention, horizon=7)
print(f"rollout output: means {tuple(means.shape)}, sigmas {tuple(sigmas.shape)}")

print("\n== KRCG retrieval ==")
library = KnowledgeLibrary([
    KnowledgeEntry(f"K{i}", doi=f"10.2000/constraint{i}", library="constraint",
                   embedding=rng.normal(size=16))
    for i in range(50)
])
retriever = KRCGRetriever(library, k=5)
match = retriever.match_record(rng.normal(size=16))
print("retrieved:", match["entries"], "weights:", [round(w, 3) for w in match["weights"]])

print("\n== constraint projection ==")
projector = ConstraintProjector()
x_free = rng.normal(size=4)
constraints = [LinearConstraint(a=np.ones(4), b=0.0, weight=10.0)]
proj = projector.project(x_free, constraints, lower=np.full(4, -5), upper=np.full(4, 5))
print(f"converged={proj['converged']}, residual {proj['residuals_before'][0]:+.3f} "
      f"-> {proj['residuals_after'][0]:+.3f}")

print("\n== sub-grid downscaling closure ==")
sub = subgrid_downscale(parent_value=30.0, corrections=rng.normal(size=25),
                        weights=np.ones(25))
print(f"parent=30.0, weighted mean of sub-cells={np.mean(sub):.10f}")

print("\n== uncertainty decomposition ==")
member_means = means.unsqueeze(0) + 0.1 * torch.randn(5, *means.shape)
member_sigmas = sigmas.unsqueeze(0).expand(5, *sigmas.shape)
unc = decompose_uncertainty(member_means, member_sigmas)
print(f"epistemic mean={unc['epistemic'].mean():.4f}, "
      f"aleatoric mean={unc['aleatoric'].mean():.4f}")

print("\n== statistical protocol ==")
cells = grid.n_valid
model_err = rng.normal(1.0, 0.3, size=cells)
baseline_err = model_err + rng.normal(0.05, 0.2, size=cells)
family = {}
for domain in ("thermal", "air_quality", "building_energy", "vegetation"):
    test = paired_cluster_test(model_err, baseline_err, blocks, seed=hash(domain) % 2**32)
    family[domain] = test["p"]
    print(f"{domain}: diff={test['mean_diff']:+.4f} CI={tuple(round(c, 4) for c in test['ci'])} "
          f"d={test['cohens_d']:.2f} n={test['n_clusters']}")
print("Holm-adjusted:", {k: round(v, 4) for k, v in holm_correction(family).items()})

print("\n== calibration report ==")
target = rng.normal(size=1000)
report = calibration_report(np.zeros(1000), np.ones(1000), target)
print(f"coverage={report['empirical_coverage']:.3f} (nominal {report['nominal_coverage']}), "
      f"ECE={report['ece']:.4f}")

print("\n== runtime benchmark logging ==")
bench = RuntimeBenchmark("synthville_case", log_path="runs/synthetic_demo.jsonl",
                         warmup_runs=2)
for i in range(7):
    bench.run(lambda: model.rollout(obs, edge_index, intervention, horizon=7), i)
print(bench.summary())

print("\nAll stages completed.")
