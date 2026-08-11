"""Training loss: prediction NLL + grounding + calibration.

L = lambda_1 * NLL + lambda_2 * (L_ground + L_struct) + lambda_3 * calibration
with lambda = (0.4, 0.4, 0.2) and calibration quantiles {0.1, ..., 0.9}.
"""

import torch

QUANTILES = torch.arange(0.1, 0.91, 0.1)


def prediction_nll(mean: torch.Tensor, sigma: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    var = sigma ** 2
    return torch.mean((mean - target) ** 2 / (2 * var) + 0.5 * torch.log(var))


def calibration_loss(mean: torch.Tensor, sigma: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Mean absolute deviation between nominal and empirical quantile coverage."""
    z = (target - mean) / sigma
    normal = torch.distributions.Normal(0.0, 1.0)
    loss = torch.zeros((), device=mean.device)
    for q in QUANTILES.to(mean.device):
        threshold = normal.icdf(q)
        empirical = (z <= threshold).float().mean()
        loss = loss + torch.abs(q - empirical)
    return loss / len(QUANTILES)


def total_loss(
    mean: torch.Tensor,
    sigma: torch.Tensor,
    target: torch.Tensor,
    ground_loss: torch.Tensor,
    struct_loss: torch.Tensor,
    lambdas: tuple[float, float, float] = (0.4, 0.4, 0.2),
) -> torch.Tensor:
    l1, l2, l3 = lambdas
    return (
        l1 * prediction_nll(mean, sigma, target)
        + l2 * (ground_loss + struct_loss)
        + l3 * calibration_loss(mean, sigma, target)
    )
