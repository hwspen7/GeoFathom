"""Conservative source-grid instance refinement and overlap diagnostics."""
import numpy as np


def compact_ids(labels):
    ids = np.asarray(labels)
    if ids.ndim != 2 or not ids.size or not np.issubdtype(ids.dtype, np.integer) or np.any(ids < 0):
        raise ValueError("Expected nonnegative integer instance grid.")
    values = np.unique(ids)
    if len(values) > 20001:
        raise ValueError("Instance count exceeds refinement budget.")
    return (np.searchsorted(values, ids) + int(values[0] != 0)).astype(np.int32)


def merge_fragments(labels, probability, boundary=None, *, fraction=.25, ridge_limit=.35):
    """Merge only small adjacent regions across weak ridges, never erase foreground.

    One deterministic pass; no detached components or strongly supported walls
    are merged. Areas are measured in native source pixels, not physical units.
    """
    ids = compact_ids(labels)
    p = np.asarray(probability, np.float32)
    b = np.zeros(ids.shape, np.float32) if boundary is None else np.asarray(boundary, np.float32)
    if (p.shape != ids.shape or b.shape != ids.shape or not 0 < fraction <= .5
            or not 0 <= ridge_limit <= 1 or not np.isfinite(p).all() or not np.isfinite(b).all()
            or np.any((p < 0) | (p > 1)) or np.any((b < 0) | (b > 1))):
        raise ValueError("Invalid refinement fields or limits.")
    n = int(ids.max()) + 1
    areas = np.bincount(ids.ravel(), minlength=n)
    pairs, ridge, strength = [], [], []
    for a, c, pa, pc, ba, bc in ((ids[:-1], ids[1:], p[:-1], p[1:], b[:-1], b[1:]),
                                  (ids[:, :-1], ids[:, 1:], p[:, :-1], p[:, 1:], b[:, :-1], b[:, 1:])):
        valid = (a > 0) & (c > 0) & (a != c)
        pairs.append(np.minimum(a[valid], c[valid]).astype(np.int64)*n + np.maximum(a[valid], c[valid]))
        ridge.append(np.maximum(ba[valid], bc[valid]))
        strength.append(np.minimum(pa[valid], pc[valid]))
    codes, inverse, count = np.unique(np.concatenate(pairs), return_inverse=True, return_counts=True)
    means = np.bincount(inverse, weights=np.concatenate(ridge))/count
    support = np.bincount(inverse, weights=np.concatenate(strength))/count
    parent = np.arange(n, dtype=np.int32)
    choices = {}
    for code, length, wall, prob in zip(codes, count, means, support):
        a, c = divmod(int(code), n)
        small, large = (a, c) if areas[a] < areas[c] else (c, a)
        if (areas[small] > fraction*areas[large] or length < 2 or wall > ridge_limit
                or prob < .45 or length < .15*np.sqrt(areas[small])):
            continue
        rank = (float(length)*(1-float(wall))*float(prob), int(areas[large]), -large)
        if small not in choices or rank > choices[small][0]:
            choices[small] = (rank, large)
    # Strictly increasing area prevents cycles; the root is assigned once.
    for small in sorted(choices, key=lambda k: (-areas[k], k)):
        parent[small] = parent[choices[small][1]]
    return compact_ids(parent[ids])


def overlap_diagnostics(predicted, reference, *, minimum_pixels=9):
    """Count overlap patterns, not mutually exclusive error causes or IoU matches."""
    p, r = compact_ids(predicted), compact_ids(reference)
    if p.shape != r.shape or minimum_pixels < 1:
        raise ValueError("Diagnostic grids must match.")
    pa = np.bincount(p.ravel()); ra = np.bincount(r.ravel())
    p = np.where((p > 0) & (pa[p] >= minimum_pixels), p, 0)
    p = compact_ids(p); pa = np.bincount(p.ravel())
    n = int(r.max()) + 1
    both = (p > 0) & (r > 0)
    code, inter = np.unique(p[both].astype(np.int64)*n+r[both], return_counts=True)
    pi, ri = code//n, code%n
    p_overlap = np.bincount(pi, weights=inter, minlength=len(pa))
    r_overlap = np.bincount(ri, weights=inter, minlength=len(ra))
    significant = (inter >= .1*pa[pi]) & (inter >= .1*ra[ri])
    p_degree = np.bincount(pi[significant], minlength=len(pa))
    r_degree = np.bincount(ri[significant], minlength=len(ra))
    return {"predicted": len(pa)-1, "reference": len(ra)-1,
            "predicted_without_overlap": int(np.count_nonzero(p_overlap[1:] == 0)),
            "reference_without_overlap": int(np.count_nonzero(r_overlap[1:] == 0)),
            "possible_merges": int(np.count_nonzero(p_degree[1:] >= 2)),
            "possible_splits": int(np.count_nonzero(r_degree[1:] >= 2)),
            "significant_overlap_fraction": .1}


def hybrid_fields(flips, multiscale, *, scale_weight=.35):
    """Combine aligned probability fields; retain flip-aligned auxiliary heads."""
    if not 0 <= scale_weight <= 1 or not np.array_equal(flips["valid"], multiscale["valid"]):
        raise ValueError("Hybrid source support or weight is invalid.")
    valid = flips["valid"]
    a, b = flips["probability"], multiscale["probability"]
    if a.shape != valid.shape or b.shape != valid.shape:
        raise ValueError("Hybrid fields must share the source grid.")
    for f in (a, b):
        if not np.isfinite(f[valid]).all() or np.any((f[valid] < 0) | (f[valid] > 1)):
            raise ValueError("Invalid hybrid probabilities.")
    return {**flips, "probability": np.where(valid, (1-scale_weight)*a+scale_weight*b, -1).astype(np.float32)}


def joint_ridge(probability, boundary, distance, valid):
    """Weak local valleys complement the learned wall head without replacing it."""
    from scipy import ndimage as ndi
    p = np.asarray(probability, np.float32)
    valid = np.asarray(valid, bool)
    b = np.zeros(p.shape, np.float32) if boundary is None else np.asarray(boundary, np.float32)
    d = np.zeros(p.shape, np.float32) if distance is None else np.asarray(distance, np.float32)
    if (p.shape != valid.shape or b.shape != p.shape or d.shape != p.shape
            or not all(np.isfinite(f[valid]).all() for f in (p,b,d))
            or np.any((p[valid]<0)|(p[valid]>1)) or np.any((b[valid]<0)|(b[valid]>1))
            or np.any((d[valid]<-1)|(d[valid]>1))):
        raise ValueError("Invalid ridge fields.")
    safe = np.where(valid, p, 0)
    valley = np.maximum(ndi.maximum_filter(safe, size=3, mode="nearest")-safe, 0)
    weak = np.minimum(.49, .7*valley + .25*np.maximum(-d, 0))
    return np.where(valid, np.maximum(b, weak), 0).astype(np.float32)


def refine_mask(probability, valid, threshold, boundary=None):
    """One-pixel, confidence-gated edge correction; retain enclosed holes.

    The raw probability remains unchanged for calibration. This is an opt-in
    mask candidate, not a topology guarantee or polygon regularizer.
    """
    from scipy import ndimage as ndi
    p = np.asarray(probability, np.float32)
    valid = np.asarray(valid, bool)
    b = np.zeros(p.shape, np.float32) if boundary is None else np.asarray(boundary, np.float32)
    if (p.ndim != 2 or p.shape != valid.shape or b.shape != p.shape or not 0 < threshold < 1
            or not np.isfinite(p[valid]).all() or not np.isfinite(b[valid]).all()
            or np.any((p[valid]<0)|(p[valid]>1)) or np.any((b[valid]<0)|(b[valid]>1))):
        raise ValueError("Invalid mask refinement fields.")
    mask = valid & (p >= threshold)
    kernel = np.ones((3,3), np.uint8); kernel[1,1] = 0
    neighbors = ndi.convolve(mask.astype(np.uint8), kernel, mode="constant", cval=0)
    enclosed = ndi.binary_fill_holes(mask) & ~mask
    add = valid & ~mask & ~enclosed & (neighbors >= 6) & (p >= threshold-.08) & (b < .4)
    remove = mask & (neighbors <= 2) & (p < threshold+.08) & (b >= .35)
    return (mask | add) & ~remove


def grouped_temperature_nll(groups, temperatures):
    """Exact leave-one-source-group-out NLL from additive grid losses."""
    if len(groups) < 2:
        return {"evaluated": False, "reason": "At least two source groups required."}
    losses = np.sum([g.losses for g in groups.values()], axis=0)
    count = sum(g.count for g in groups.values())
    positive = sum(g.positive for g in groups.values())
    raw = temperatures.index(1.)
    selected_loss = 0.; folds = []
    for name, group in sorted(groups.items()):
        if not 0 < positive-group.positive < count-group.count or not group.count:
            return {"evaluated": False, "reason": "Each training fold must contain both classes."}
        train = losses-group.losses
        idx = min(range(len(temperatures)), key=lambda i: (train[i], abs(temperatures[i]-1.)))
        selected_loss += float(group.losses[idx])
        folds.append({"held_out_group": name, "temperature": temperatures[idx], "pixels": group.count})
    return {"evaluated": True, "groups": len(folds), "raw_nll": float(losses[raw]/count),
            "crossfit_nll": selected_loss/count, "folds": folds}


def spatial_view_fusion(primary_flips, primary_scale, secondary_flips, secondary_scale):
    """Bounded local weighting by cross-view consistency, not correctness probability."""
    from scipy import ndimage as ndi
    a = hybrid_fields(primary_flips, primary_scale)
    b = hybrid_fields(secondary_flips, secondary_scale)
    valid = a["valid"]
    if not np.array_equal(valid, b["valid"]):
        raise ValueError("Spatial ensemble source supports differ.")
    support = ndi.uniform_filter(valid.astype(np.float32), size=9, mode="constant")

    def instability(flip, scale):
        delta = np.where(valid, np.abs(flip["probability"]-scale["probability"]), 0)
        return ndi.uniform_filter(delta, size=9, mode="constant")/np.maximum(support, 1e-6)

    log_odds = np.clip(3*(instability(primary_flips, primary_scale)-instability(secondary_flips, secondary_scale)),
                       -np.log(2.), np.log(2.))
    weight = 1/(1+np.exp(-log_odds))
    probability = (1-weight)*a["probability"]+weight*b["probability"]
    return {**a, "probability": np.where(valid, probability, -1).astype(np.float32)}
