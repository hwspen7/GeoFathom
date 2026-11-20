"""Georeferenced segmentation: click -> mask -> polygon -> WGS84 area."""

import math
from pathlib import Path
from typing import Literal

import numpy as np
from rasterio.features import shapes
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape

from geometry.mask import seeded_region
from geometry.measure import GeometryError, measure_geometry
from imagery.raster import RasterError, read_rgb_window
from .sam import sam_mask


def _vectorize(
    mask: np.ndarray, affine, source_crs: str,
) -> dict:
    if int(mask.sum()) < 4:
        raise RasterError("Selection is smaller than four source pixels.")
    polygons = [
        shape(geom) for geom, value in shapes(
            mask.astype(np.uint8),
            mask=mask.astype(bool),
            transform=affine,
            connectivity=4,
        ) if value == 1
    ]
    if not polygons:
        raise RasterError("Segmentation did not produce a usable polygon.")
    # A single click targets one contiguous feature, not every disconnected mask.
    chosen = max(polygons, key=lambda polygon: polygon.area)
    if not chosen.is_valid:
        chosen = chosen.buffer(0)
    if chosen.is_empty:
        raise RasterError("Segmentation produced invalid geometry.")
    converted = transform_geom(
        source_crs, "EPSG:4326", mapping(chosen), antimeridian_cutting=True, precision=8,
    )
    if converted.get("type") not in {"Polygon", "MultiPolygon"}:
        raise RasterError("No polygon could be derived from the selected pixels.")
    try:
        measurement = measure_geometry(converted)
    except GeometryError as error:
        raise RasterError(f"Vectorized polygon could not be measured: {error}") from error
    return {"geometry": converted, "measurement": measurement}


def trace_raster(
    path: Path,
    image_id: str,
    longitude: float,
    latitude: float,
    method: Literal["color", "sam2"] = "color",
    tolerance: int = 20,
    window_size: int = 512,
) -> dict:
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise RasterError("Click coordinates must be finite.")
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise RasterError("Click is outside WGS84 coordinate bounds.")
    image, seed_x, seed_y, affine, crs = read_rgb_window(
        path, longitude, latitude, window_size,
    )
    confidence = None
    if method == "color":
        mask, engine = seeded_region(image, seed_x, seed_y, tolerance)
        model_id = None
    elif method == "sam2":
        mask, confidence, model_id = sam_mask(image, seed_x, seed_y)
        engine = "sam2-prompted-image-mask"
    else:
        raise RasterError("Unknown trace provider.")

    if not mask[seed_y, seed_x]:
        raise RasterError("The prediction does not cover the clicked point.")
    if not np.any(mask):
        raise RasterError("No mask was found around the selected point.")
    output = _vectorize(mask, affine, crs)
    touches_edge = bool(
        np.any(mask[0, :]) or np.any(mask[-1, :])
        or np.any(mask[:, 0]) or np.any(mask[:, -1])
    )
    return {
        **output,
        "image_id": image_id,
        "provider": method,
        "engine": engine,
        "model_id": model_id,
        "confidence": confidence,
        "pixel_count": int(mask.sum()),
        "window_shape": [int(image.shape[1]), int(image.shape[0])],
        "source_crs": crs,
        "boundary_status": "estimated_from_imagery",
        "geometry_crs": "EPSG:4326",
        "window_truncated": touches_edge,
        "source": "User-supplied georeferenced GeoTIFF",
        "warning": (
            "Segmentation touches the analysis-window edge; the feature may be incomplete. "
            "Increase the window size and verify the outline."
            if touches_edge else
            "Image-derived boundary is an estimate. Review and edit before relying on its area."
        ),
    }
