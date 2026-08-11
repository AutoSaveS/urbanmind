"""Cross-domain coupling tensor C.

The coupling structure is *initialized and regularized by literature-derived priors*
(C_prior with directional sign constraints) and refined from data -- the manuscript
does not claim unsupervised discovery. Entries are model-internal association
patterns, consistent with (but not evidence for) known physical pathways.
"""

import torch
from torch import nn


class CouplingTensor(nn.Module):
    """Learnable D x D domain-coupling matrix with prior regularization.

    prior: (D, D) literature-derived prior magnitudes (0 where no documented pathway).
    sign: (D, D) directional constraints in {-1, 0, +1}; 0 leaves the sign free.
    """

    def __init__(self, prior: torch.Tensor, sign: torch.Tensor, prior_weight: float = 0.1):
        super().__init__()
        assert prior.shape == sign.shape and prior.shape[0] == prior.shape[1]
        self.register_buffer("prior", prior)
        self.register_buffer("sign", sign)
        self.prior_weight = prior_weight
        self.raw = nn.Parameter(prior.clone())

    def forward(self) -> torch.Tensor:
        c = self.raw
        # Enforce directional constraints where the literature fixes the sign.
        constrained = torch.where(self.sign != 0, self.sign * torch.abs(c), c)
        return constrained

    def prior_loss(self) -> torch.Tensor:
        """L_struct: keeps refined couplings anchored to the documented structure."""
        return self.prior_weight * torch.mean((self.forward() - self.prior) ** 2)
