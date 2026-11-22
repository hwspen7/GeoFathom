"""Priority-flood conditioning for bounded local D8 hydrology.

A representable downhill gradient resolves flats and filled depressions without
modifying the original DEM asset. NoData is never replaced with invented heights.
"""
from heapq import heappop, heappush
from math import inf, nextafter

import numpy as np

from .cancellation import checkpoint

_NEIGHBORS = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
              (0, 1), (1, -1), (1, 0), (1, 1))


def condition_dem(elevations, valid, cancel=None):
    """Return a hydrologically connected work grid and conditioning metrics.

    Grid edges and cells next to NoData act as outlets. Priority-flood fills
    sinks; a one-ULP gradient resolves flats for strict-downhill D8 routing.
    This is a screening model: disconnected source coverage remains unknown.
    """
    if elevations.ndim != 2 or elevations.shape != valid.shape or not valid.any():
        raise ValueError("Conditioning requires a nonempty, aligned 2-D DEM mask.")
    if not np.isfinite(elevations[valid]).all():
        raise ValueError("Valid DEM cells must contain finite elevations.")
    height, width = elevations.shape
    working = np.asarray(elevations, dtype=np.float64).copy()
    visited = ~valid.copy()
    outlets = np.zeros_like(valid, dtype=bool)
    outlets[0, :] |= valid[0, :]
    outlets[-1, :] |= valid[-1, :]
    outlets[:, 0] |= valid[:, 0]
    outlets[:, -1] |= valid[:, -1]
    # Unknown neighbors are treated as outlets, never as filled terrain.
    for dr, dc in _NEIGHBORS:
        r0, r1 = max(0, -dr), min(height, height - dr)
        c0, c1 = max(0, -dc), min(width, width - dc)
        outlets[r0:r1, c0:c1] |= (
            valid[r0:r1, c0:c1]
            & ~valid[r0+dr:r1+dr, c0+dc:c1+dc]
        )
    heap = []
    for r, c in zip(*np.nonzero(outlets)):
        visited[r, c] = True
        heappush(heap, (float(working[r, c]), int(r), int(c)))
    traversed = 0
    while heap:
        elevation, r, c = heappop(heap)
        traversed += 1
        if traversed % 4096 == 0:
            checkpoint(cancel)
        for dr, dc in _NEIGHBORS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < height and 0 <= cc < width) or visited[rr, cc]:
                continue
            visited[rr, cc] = True
            if not valid[rr, cc]:
                continue
            next_height = max(float(working[rr, cc]), nextafter(elevation, inf))
            working[rr, cc] = next_height
            heappush(heap, (next_height, rr, cc))
    changes = working[valid] - np.asarray(elevations, dtype=np.float64)[valid]
    return working, {
        "conditioned_cells": int(np.count_nonzero(changes > 0)),
        "maximum_fill_depth_m": float(changes.max(initial=0)),
        "total_fill_depth_m": float(changes.sum()),
        "outlet_cells": int(outlets.sum()),
    }
