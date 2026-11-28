"""Bounded probability fusion; primary model retains native instance heads."""
import numpy as np

from imagery.raster import RasterError


def fuse_probabilities(primary, secondary, secondary_weight, valid=None):
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
    out = np.full(a.shape, -1., np.float32)
    out[valid] = ((1-secondary_weight)*a[valid].astype(np.float64)
                  + secondary_weight*b[valid].astype(np.float64)).astype(np.float32)
    return out


def compatible_members(primary, secondary):
    for config in (primary, secondary):
        if (config["task"] != "building_extraction" or config["classes"] != ["background", "building"]
                or config["output_type"] not in ("binary_logits", "binary_probability")):
            raise RasterError("Ensemble members must declare binary building probabilities.")
    if sorted(primary["bands"]) != sorted(secondary["bands"]):
        raise RasterError("Ensemble members must use the same source band support.")
