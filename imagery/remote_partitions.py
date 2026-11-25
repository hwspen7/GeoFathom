"""Deterministic contiguous spatial folds with label-independent block buffers."""
import numpy as np
from scipy.spatial import cKDTree

from analysis.science_raster import require


def spatial_partitions(shape, transform, block_m, folds, buffer_blocks=0):
    """Partition occupied coordinate blocks before consulting any class labels.

    Recursive spatial bisection keeps folds compact. Buffer distances are
    Chebyshev distances between actual block coordinates, including diagonals.
    Repeating modulo patterns are unsuitable here: dilating them can remove
    every training block even when a large scene contains ample observations.
    """
    require(3 <= folds <= 10 and float(folds).is_integer(), "Use 3–10 spatial folds.")
    require(np.isfinite(block_m) and block_m > 0, "Spatial block width must be positive.")
    require(buffer_blocks in (0, 1), "Use zero or one spatial buffer block.")
    require(transform.a > 0 and transform.e < 0 and transform.b == transform.d == 0,
            "Spatial folds require a north-up grid.")
    row, col = np.indices(shape)
    # Anchor blocks to projected coordinates rather than an arbitrary crop origin.
    bx = np.floor((transform.c + (col + .5) * transform.a) / block_m).astype(np.int64)
    by = np.floor((transform.f + (row + .5) * transform.e) / block_m).astype(np.int64)
    blocks, inverse = np.unique(np.column_stack((bx.ravel(), by.ravel())), axis=0,
                                return_inverse=True)
    require(len(blocks) >= folds, "Each spatial fold needs an occupied block; reduce block size.")
    assigned = np.empty(len(blocks), dtype=np.int16)

    def split(ids, first, count):
        if count == 1:
            assigned[ids] = first
            return
        points = blocks[ids]
        axis = int(np.argmax(np.ptp(points, axis=0)))
        order = np.lexsort((points[:, 1-axis], points[:, axis]))
        left = count // 2
        cut = max(left, min(len(ids) - (count-left), len(ids) * left // count))
        split(ids[order[:cut]], first, left)
        split(ids[order[cut:]], first+left, count-left)

    split(np.arange(len(blocks)), 0, int(folds))
    fold = assigned[inverse].reshape(shape)
    excluded = []
    for j in range(int(folds)):
        if buffer_blocks:
            # Query block centers, not fold-number arithmetic or class labels.
            distance, _ = cKDTree(blocks[assigned == j]).query(blocks, p=np.inf)
            bad = distance <= buffer_blocks
        else:
            bad = assigned == j
        excluded.append(bad[inverse].reshape(shape))
    return fold, excluded
