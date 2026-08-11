import numpy as np
import pytest
import torch

from urbanmind.data.grid import CityGrid, make_spatial_blocks
from urbanmind.data.temporal import Provenance, harmonize_series
from urbanmind.data.tracks import Record, assign_tracks, verify_disjoint
from urbanmind.eval.calibration import calibration_report
from urbanmind.eval.stats import holm_correction, paired_cluster_test
from urbanmind.model.grounding import ConstraintProjector, LinearConstraint, subgrid_downscale
from urbanmind.model.world_model import GraphWorldModel


def test_spatial_blocks_cover_all_cells():
    grid = CityGrid("t", 30, 30)
    blocks = make_spatial_blocks(grid, block_cells=10)
    assert len(blocks) == grid.n_valid
    assert blocks.max() + 1 == 9


def test_track_split_disjoint_by_doi_and_site():
    records = [
        Record("a", doi="10.1/x", study_site="s1", track="B"),
        Record("b", doi="10.1/x", study_site="s2", track="B"),  # same DOI as a
        Record("c", doi="10.1/y", study_site="s2", track="B"),  # same site as b
        Record("d", doi="10.1/z", study_site="s9", track="B"),
    ]
    assignment = assign_tracks(records)
    verify_disjoint(records, assignment)
    # a, b, c are transitively linked and must land in the same subset.
    assert assignment["a"] == assignment["b"] == assignment["c"]


def test_harmonization_flags_provenance():
    series = harmonize_series(np.array([0, 30]), np.array([1.0, 2.0]),
                              target_length=31, native_step=30)
    assert series.provenance[0] == Provenance.MEASURED
    assert (series.provenance[1:30] == Provenance.RULE_DOWNSCALED).all()


def test_downscale_closure_is_exact():
    sub = subgrid_downscale(10.0, np.random.default_rng(1).normal(size=16), np.ones(16))
    assert np.mean(sub) == pytest.approx(10.0, abs=1e-9)


def test_projection_reduces_residual():
    projector = ConstraintProjector()
    x = np.array([2.0, 2.0])
    out = projector.project(x, [LinearConstraint(np.ones(2), 0.0, weight=100.0)])
    assert abs(out["residuals_after"][0]) < abs(out["residuals_before"][0])


def test_rollout_shapes():
    model = GraphWorldModel(obs_dim=8)
    obs = torch.randn(50, 8)
    edges = torch.randint(0, 50, (2, 200))
    intervention = torch.zeros(50, 4)
    means, sigmas = model.rollout(obs, edges, intervention, horizon=3)
    assert means.shape == (3, 50, 4)
    assert (sigmas > 0).all()


def test_cluster_test_and_holm():
    rng = np.random.default_rng(0)
    clusters = np.repeat(np.arange(20), 10)
    a = rng.normal(0, 1, 200)
    b = a + 0.5  # b is clearly worse
    result = paired_cluster_test(a, b, clusters)
    assert result["ci"][1] < 0
    adjusted = holm_correction({"t1": 0.01, "t2": 0.04, "t3": 0.30})
    assert adjusted["t1"] <= adjusted["t2"] <= adjusted["t3"]


def test_calibration_well_specified_model():
    rng = np.random.default_rng(0)
    target = rng.normal(size=5000)
    report = calibration_report(np.zeros(5000), np.ones(5000), target)
    assert report["empirical_coverage"] == pytest.approx(0.9, abs=0.03)
    assert report["ece"] < 0.03
