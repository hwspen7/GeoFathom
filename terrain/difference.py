"""Co-registered DEM change raster and cell-area statistics."""
import math

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

from imagery.raster import RasterError
from .engine import _check_dem
from .professional import raster_product
from .cancellation import checkpoint
from .vertical import vertical_datum, check_vertical_compatibility


def compare_dem(primary, valid, affine, crs, reference_path, cancel=None, primary_path=None):
    """Compare two source DEMs on the primary projected grid.

    A reference DEM is reprojected to the current study-area grid with nodata
    respected. Resampling supplies comparable cells, not new source accuracy.
    The sign convention is primary minus reference: positive means higher.
    """
    if reference_path is None:
        raise RasterError("Choose a second DEM to compare.")
    checkpoint(cancel)
    with rasterio.open(reference_path) as source:
        _check_dem(source)
        reference_datum=vertical_datum(source)
        primary_datum=None
        if primary_path is not None:
            with rasterio.open(primary_path) as primary_source:
                _check_dem(primary_source)
                primary_datum=vertical_datum(primary_source)
                check_vertical_compatibility([primary_datum,reference_datum])
        if source.count != 1:
            raise RasterError("DEM comparison requires a single elevation band.")
        reference = np.full(primary.shape, np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(source, 1),
            destination=reference,
            src_nodata=source.nodata,
            dst_nodata=np.nan,
            dst_transform=affine,
            dst_crs=crs,
            resampling=Resampling.bilinear,
            num_threads=1,
            warp_mem_limit=32,
        )
    checkpoint(cancel)
    common = valid & np.isfinite(reference)
    if not common.any():
        raise RasterError("The two DEMs have no overlapping valid grid cells.")
    delta = np.full(primary.shape, np.nan, dtype=np.float64)
    delta[common] = primary[common] - reference[common]
    diff = delta[common]
    area = abs(affine.a * affine.e)
    positives = np.maximum(diff, 0)
    negatives = np.maximum(-diff, 0)
    metrics = {
        "comparison_cells": int(common.sum()),
        "increased_cells": int(np.count_nonzero(diff>0)),
        "decreased_cells": int(np.count_nonzero(diff<0)),
        "unchanged_cells": int(np.count_nonzero(diff==0)),
        # Metadata agreement is not independent vertical-datum verification.
        "datum_labels_match": int(primary_datum is not None and reference_datum is not None
                                  and primary_datum==reference_datum),
        "comparison_coverage_pct": 100 * int(common.sum()) / max(1, int(valid.sum())),
        "elevation_change_mean_m": float(diff.mean()),
        "elevation_change_min_m": float(diff.min()),
        "elevation_change_max_m": float(diff.max()),
        "elevation_change_rmse_m": float(np.sqrt(np.mean(diff ** 2))),
        "elevation_change_mae_m": float(np.mean(np.abs(diff))),
        "raised_volume_m3": float(math.fsum(positives) * area),
        "lowered_volume_m3": float(math.fsum(negatives) * area),
        "net_elevation_volume_m3": float(math.fsum(diff) * area),
    }
    return raster_product(delta, "dem_difference", affine, crs, cancel,
                          source_datum=primary_datum,
                          reference_datum=reference_datum), metrics
