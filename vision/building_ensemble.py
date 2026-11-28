"""Bounded probability fusion; primary model retains native instance heads."""
import numpy as np

from imagery.raster import RasterError


def fuse_probabilities(primary, secondary, secondary_weight, valid=None, *, mode="fixed"):
    """Fuse same-grid raw probabilities; reject mismatched support rather than extrapolate."""
    a, b = np.asarray(primary), np.asarray(secondary)
    if a.shape != b.shape or not 0 <= secondary_weight <= 1:
        raise RasterError("Invalid ensemble probability grid or weight.")
    valid = np.ones(a.shape, bool) if valid is None else np.asarray(valid, bool)
    if valid.shape != a.shape:
        raise RasterError("Ensemble validity does not match the probability grid.")
    for field in (a, b):
        p = field[valid]
        if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
            raise RasterError("Ensemble probabilities must be finite and within [0,1].")
    if mode not in ("fixed", "confidence"):
        raise RasterError("Unsupported ensemble fusion mode.")
    av, bv = a[valid].astype(np.float64), b[valid].astype(np.float64)
    weight = secondary_weight
    if mode == "confidence":
        # Conservative confidence proxy, not a calibrated correctness estimate.
        # The maximum local odds multiplier is two; retain the validated prior.
        primary_strength = 1+np.abs(2*av-1)
        secondary_strength = 1+np.abs(2*bv-1)
        weight = (secondary_weight*secondary_strength /
                  ((1-secondary_weight)*primary_strength+secondary_weight*secondary_strength))
    out = np.full(a.shape, -1., np.float32)
    out[valid] = ((1-weight)*av + weight*bv).astype(np.float32)
    return out


def uncertainty_fields(primary, secondary, fused, valid):
    """Native-grid disagreement and normalized binary entropy, not error probabilities."""
    valid = np.asarray(valid, bool)
    a, b, p = (np.asarray(field) for field in (primary, secondary, fused))
    if any(field.shape != valid.shape for field in (a, b, p)):
        raise RasterError("Uncertainty fields must share one source grid.")
    for field in (a, b, p):
        if not np.isfinite(field[valid]).all() or np.any((field[valid]<0)|(field[valid]>1)):
            raise RasterError("Uncertainty fields require valid probabilities.")
    disagreement = np.full(valid.shape, -1., np.float32)
    entropy = disagreement.copy()
    disagreement[valid] = np.abs(a[valid]-b[valid])
    q = p[valid].astype(np.float64)
    entropy[valid] = -(q*np.log2(np.maximum(q, 1e-15)) +
                      (1-q)*np.log2(np.maximum(1-q, 1e-15)))
    return disagreement, entropy


def compatible_members(primary, secondary):
    for config in (primary, secondary):
        if (config["task"] != "building_extraction" or config["classes"] != ["background", "building"]
                or config["output_type"] not in ("binary_logits", "binary_probability")):
            raise RasterError("Ensemble members must declare binary building probabilities.")
    if sorted(primary["bands"]) != sorted(secondary["bands"]):
        raise RasterError("Ensemble members must use the same source band support.")
