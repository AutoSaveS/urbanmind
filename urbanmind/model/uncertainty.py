"""Epistemic-aleatoric uncertainty decomposition (deep ensembles)."""

import torch


def decompose_uncertainty(
    member_means: torch.Tensor, member_sigmas: torch.Tensor
) -> dict[str, torch.Tensor]:
    """Decompose ensemble predictions into epistemic and aleatoric components.

    member_means, member_sigmas: (M, ..., D) over M ensemble members.

    epistemic  = variance of member means (model disagreement)
    aleatoric  = mean of member variances (data noise, incl. harmonization inflation)
    """
    epistemic = member_means.var(dim=0, unbiased=False)
    aleatoric = (member_sigmas ** 2).mean(dim=0)
    total = epistemic + aleatoric
    return {
        "mean": member_means.mean(dim=0),
        "epistemic": epistemic,
        "aleatoric": aleatoric,
        "total_sigma": total.sqrt(),
    }
