"""Stage 1: multi-scale graph world model.

Latent urban states evolve on a heterogeneous spatial graph; the four domain channels
co-evolve through the coupling tensor, and interventions condition the dynamics via
FiLM (feature-wise linear modulation). The rollout is an internal computational
representation; evaluated outputs are the decoded daily fields.
"""

from __future__ import annotations

import torch
from torch import nn

from .coupling import CouplingTensor


class GraphMessagePassing(nn.Module):
    """Mean-aggregation message passing over a fixed edge list."""

    def __init__(self, dim: int):
        super().__init__()
        self.msg = nn.Linear(dim, dim)
        self.upd = nn.GRUCell(dim, dim)

    def forward(self, h: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        # h: (N, dim); edge_index: (2, E) with rows (src, dst)
        src, dst = edge_index
        messages = self.msg(h[src])
        agg = torch.zeros_like(h).index_add_(0, dst, messages)
        deg = torch.zeros(h.size(0), device=h.device).index_add_(
            0, dst, torch.ones_like(dst, dtype=h.dtype)
        ).clamp(min=1).unsqueeze(-1)
        return self.upd(agg / deg, h)


class FiLMConditioner(nn.Module):
    """Maps an intervention vector to per-channel scale and shift."""

    def __init__(self, intervention_dim: int, dim: int):
        super().__init__()
        self.net = nn.Linear(intervention_dim, 2 * dim)

    def forward(self, h: torch.Tensor, intervention: torch.Tensor) -> torch.Tensor:
        gamma, beta = self.net(intervention).chunk(2, dim=-1)
        return (1 + gamma) * h + beta


class GraphWorldModel(nn.Module):
    def __init__(
        self,
        n_domains: int = 4,
        obs_dim: int = 8,
        latent_dim: int = 64,
        intervention_dim: int = 4,
        coupling_prior: torch.Tensor | None = None,
        coupling_sign: torch.Tensor | None = None,
    ):
        super().__init__()
        self.n_domains = n_domains
        self.encoder = nn.Sequential(
            nn.Linear(obs_dim, latent_dim), nn.GELU(), nn.Linear(latent_dim, latent_dim)
        )
        self.gnn = GraphMessagePassing(latent_dim)
        self.film = FiLMConditioner(intervention_dim, latent_dim)
        prior = coupling_prior if coupling_prior is not None else torch.eye(n_domains)
        sign = coupling_sign if coupling_sign is not None else torch.zeros(n_domains, n_domains)
        self.coupling = CouplingTensor(prior, sign)
        self.domain_proj = nn.Linear(latent_dim, n_domains * latent_dim)
        # Per-domain decoders return (mean, log aleatoric variance).
        self.decoders = nn.ModuleList(
            [nn.Linear(latent_dim, 2) for _ in range(n_domains)]
        )

    def encode(self, obs: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        return self.gnn(self.encoder(obs), edge_index)

    def step(
        self, h: torch.Tensor, edge_index: torch.Tensor, intervention: torch.Tensor
    ) -> torch.Tensor:
        """One rollout step: spatial propagation, cross-domain mixing, conditioning."""
        h = self.gnn(h, edge_index)
        n, d = h.shape
        per_domain = self.domain_proj(h).view(n, self.n_domains, d)
        mixed = torch.einsum("md,nds->nms", self.coupling(), per_domain)
        h = mixed.mean(dim=1)
        return self.film(h, intervention)

    def decode(self, h: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns mean (N, D) and aleatoric sigma (N, D) for the daily fields."""
        outs = [dec(h) for dec in self.decoders]
        mean = torch.stack([o[:, 0] for o in outs], dim=-1)
        sigma = torch.stack([torch.exp(0.5 * o[:, 1]) for o in outs], dim=-1)
        return mean, sigma

    def rollout(
        self,
        obs: torch.Tensor,
        edge_index: torch.Tensor,
        intervention: torch.Tensor,
        horizon: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Multi-step rollout; returns stacked means and sigmas (H, N, D)."""
        h = self.encode(obs, edge_index)
        means, sigmas = [], []
        for _ in range(horizon):
            h = self.step(h, edge_index, intervention)
            mean, sigma = self.decode(h)
            means.append(mean)
            sigmas.append(sigma)
        return torch.stack(means), torch.stack(sigmas)
