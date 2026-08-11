"""Fit the reference model on a synthetic city so the demo shows real learned
responses. Run: python demo/train_synthetic.py  (writes demo/synthetic_model.pt)

The synthetic ground truth encodes known couplings so intervention responses are
visible and physically sensible in direction: raising canopy cools the thermal
field and improves air quality; raising roof albedo lowers building energy and
temperature. The demo is labeled synthetic.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import numpy as np
import torch

from urbanmind.data.grid import CityGrid
from urbanmind.model.world_model import GraphWorldModel

SIZE = 24
OBS_DIM = 8
SEED = 7


def build_city():
    rng = np.random.default_rng(SEED)
    grid = CityGrid("synthville", SIZE, SIZE)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / SIZE

    # Static context: density high downtown (center), water body east.
    density = np.exp(-((yy - 0.5) ** 2 + (xx - 0.45) ** 2) * 6)
    water = (xx > 0.85).astype(float)
    base_canopy = 0.15 + 0.5 * (1 - density) * (1 - water)
    obs = np.stack([
        density, water, base_canopy,
        rng.normal(0, 0.05, (SIZE, SIZE)) + density,          # impervious
        yy, xx,
        rng.normal(0, 1, (SIZE, SIZE)) * 0.1,                 # noise channels
        rng.normal(0, 1, (SIZE, SIZE)) * 0.1,
    ], axis=-1).reshape(-1, OBS_DIM).astype(np.float32)

    def truth(canopy_delta: float, albedo_delta: float) -> np.ndarray:
        """Four-domain response fields under an intervention (known coupling)."""
        canopy = base_canopy + canopy_delta * (1 - water)
        thermal = 3.0 * density - 2.2 * canopy - 1.8 * albedo_delta * density - 0.8 * water
        air = 2.0 * density - 1.5 * canopy
        energy = 2.5 * density - 1.2 * albedo_delta * density - 0.4 * canopy
        veg = canopy * 2.0
        return np.stack([thermal, air, energy, veg], axis=-1).reshape(-1, 4).astype(np.float32)

    # 4-neighbour grid edges.
    idx = np.arange(SIZE * SIZE).reshape(SIZE, SIZE)
    edges = []
    for a, b in [(idx[:, :-1], idx[:, 1:]), (idx[:-1, :], idx[1:, :])]:
        edges.append(np.stack([a.ravel(), b.ravel()]))
        edges.append(np.stack([b.ravel(), a.ravel()]))
    edge_index = torch.tensor(np.concatenate(edges, axis=1), dtype=torch.long)
    return grid, torch.tensor(obs), edge_index, truth


def main():
    torch.manual_seed(SEED)
    grid, obs, edge_index, truth = build_city()
    model = GraphWorldModel(obs_dim=OBS_DIM)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3)

    rng = np.random.default_rng(SEED)
    for step in range(400):
        canopy_delta = float(rng.uniform(0, 0.3))
        albedo_delta = float(rng.uniform(0, 0.4))
        intervention = torch.tensor([canopy_delta, albedo_delta, 0.0, 0.0]).expand(obs.shape[0], -1)
        target = torch.tensor(truth(canopy_delta, albedo_delta))

        means, sigmas = model.rollout(obs, edge_index, intervention, horizon=1)
        loss = torch.mean((means[0] - target) ** 2 / (2 * sigmas[0] ** 2)
                          + torch.log(sigmas[0]))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % 100 == 0:
            rmse = torch.sqrt(torch.mean((means[0] - target) ** 2)).item()
            print(f"step {step}: loss {loss.item():.4f} rmse {rmse:.4f}")

    torch.save({"state_dict": model.state_dict(), "obs": obs,
                "edge_index": edge_index, "size": SIZE}, "demo/synthetic_model.pt")
    print("saved demo/synthetic_model.pt")


if __name__ == "__main__":
    main()
