"""Building-specific hard-example objective for mask, boundary and distance heads."""
import torch
import torch.nn.functional as F


def hard_example_loss(raw, target, positive_weight):
    """Combine class-aware BCE, per-chip hard pixels and narrow foreground emphasis.

    Signed distance is an interior-width proxy, not an independent object-size label.
    Keep a dense objective on every pixel, including empty-background chips.
    """
    mask, boundary, distance = target.unbind(dim=1)
    mask_logits, boundary_logits, distance_logits = raw.unbind(dim=1)
    probability = torch.sigmoid(mask_logits)
    errors = F.binary_cross_entropy_with_logits(mask_logits, mask,
                                                pos_weight=positive_weight, reduction="none")
    # Cap the contribution of narrow structures; detach labels, never predictions.
    narrow = 1 + mask * (1 - distance.clamp(0, 1))
    dense = (errors*narrow).sum(dim=(1, 2))/narrow.sum(dim=(1, 2))
    flattened = errors.flatten(1)
    k = max(1, flattened.shape[1]//4)
    hard = flattened.topk(k, dim=1, sorted=False).values.mean(dim=1)
    dice = 1-(2*(probability*mask).sum(dim=(1, 2))+1)/(probability.sum(dim=(1, 2))+mask.sum(dim=(1, 2))+1)
    boundary_count = boundary.sum()
    boundary_weight = ((boundary.numel()-boundary_count)/boundary_count.clamp_min(1)).clamp(1, 8)
    boundary_loss = F.binary_cross_entropy_with_logits(boundary_logits, boundary, pos_weight=boundary_weight)
    distance_error = F.smooth_l1_loss(torch.tanh(distance_logits), distance, reduction="none")
    distance_weight = 1+mask
    return (.75*dense+.25*hard+dice).mean()+.5*boundary_loss+.25*(distance_error*distance_weight).sum()/distance_weight.sum()
