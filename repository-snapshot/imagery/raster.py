"""GeoTIFF inspection, preview and georeferenced raster reads.

Rasterio/GDAL owns CRS, window IO, reprojection and raster metadata. Image
previews preserve pixel location via four WGS84 corners, including rotation.
"""

from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.windows import Window
from rasterio.warp import transform

MAX_DIMENSION = 20_000
PREVIEW_SIZE = 1024


class RasterError(ValueError):
    """Unusable or non-georeferenced raster."""


def _check(src) -> None:
    if src.driver != "GTiff":
        raise RasterError("Only GeoTIFF images are supported.")
    if not src.crs:
        raise RasterError("Raster lacks a coordinate reference system.")
    if not 1 <= src.count <= 20:
        raise RasterError("Raster must contain between 1 and 20 bands.")
    if not (1 <= src.width <= MAX_DIMENSION and 1 <= src.height <= MAX_DIMENSION):
        raise RasterError("Raster dimensions exceed the supported limit.")
    if abs(src.transform.a * src.transform.e - src.transform.b * src.transform.d) < 1e-18:
        raise RasterError("Raster has a non-invertible geographic transform.")
    # A default identity pixel transform is not a georeferencing solution.
    if src.transform.is_identity:
        raise RasterError("Raster lacks a meaningful georeferencing transform.")


def _corners(src) -> list[list[float]]:
    cols = [0, src.width, src.width, 0]
    rows = [0, 0, src.height, src.height]
    coords = [src.transform @ (col, row) for col, row in zip(cols, rows)]
    lons, lats = transform(
        src.crs, "EPSG:4326",
        [p[0] for p in coords], [p[1] for p in coords],
    )
    result = [[float(x), float(y)] for x, y in zip(lons, lats)]
    if not np.all(np.isfinite(result)):
        raise RasterError("Raster WGS84 coordinates are invalid.")
    if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in result):
        raise RasterError("Raster coordinates extend beyond valid WGS84 bounds.")
    return result


def metadata(path: Path) -> dict:
    try:
        with rasterio.open(path) as src:
            _check(src)
            corners = _corners(src)
            xs, ys = zip(*corners)
            bounds = [min(xs), min(ys), max(xs), max(ys)]
            if bounds[2] - bounds[0] >= 180:
                raise RasterError("Dateline-spanning imagery is not supported by the image overlay.")
            return {
                "width": src.width, "height": src.height, "bands": src.count,
                "dtype": src.dtypes[0],
                "crs": str(src.crs),
                "is_tiled": bool(src.is_tiled),
                "block_shapes": [list(item) for item in src.block_shapes],
                "overviews": src.overviews(1),
                "corners": corners,
                "bbox": bounds,
                "resolution": [abs(src.transform.a), abs(src.transform.e)],
                "resolution_unit": ("degree" if src.crs.is_geographic
                                    else (src.crs.linear_units or "unknown")),
                # Declared vertical references are metadata, not independent
                # verification of survey control or vertical accuracy.
                "vertical_unit": (src.units[0] or src.tags().get("VERTICAL_UNIT")
                                  or None),
                "vertical_datum": (src.tags().get("VERTICAL_DATUM")
                                   or src.tags().get("VERTICAL_REFERENCE")
                                   or None),
                "acquired_at": src.tags().get("TIFFTAG_DATETIME")
                               or src.tags().get("ACQUISITION_DATE"),
                "provenance": "User-supplied georeferenced GeoTIFF",
                "georeferencing": "Rasterio/GDAL affine transform, exported to WGS84",
            }
    except rasterio.errors.RasterioError as error:
        raise RasterError("File cannot be opened as a GeoTIFF.") from error


def _rgb(data: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
    """Convert one or three raster bands to RGB, excluding NoData from stretching."""
    if data.shape[0] == 1:
        data = np.repeat(data, 3, axis=0)
    if data.dtype == np.uint8:
        return np.ascontiguousarray(np.moveaxis(data, 0, -1))
    # Per-window robust scaling handles uint16 reflectance without requiring
    # a full-image read. Avoid division by zero on constant channels.
    converted = np.zeros(data.shape, dtype=np.uint8)
    for band in range(3):
        values = data[band].astype(np.float32)
        pixels=np.isfinite(values)
        if valid is not None:
            pixels &= valid
        finite = values[pixels]
        if finite.size == 0:
            continue
        low, high = np.percentile(finite, [2, 98])
        if high > low:
            converted[band] = np.clip((values - low) * (255.0 / (high - low)), 0, 255)
    return np.ascontiguousarray(np.moveaxis(converted, 0, -1))


def preview_png(path: Path) -> bytes:
    with rasterio.open(path) as src:
        _check(src)
        scale = min(1, PREVIEW_SIZE / max(src.width, src.height))
        width = max(1, int(src.width * scale))
        height = max(1, int(src.height * scale))
        indexes = [1, 2, 3] if src.count >= 3 else [1]
        data = src.read(
            indexes,
            out_shape=(len(indexes), height, width),
            resampling=Resampling.bilinear,
            masked=True,
        )
    # NoData and NaNs must remain transparent in the map overlay, never
    # appear as low terrain; ignore them when stretching 16/32-bit values.
    valid=(~np.ma.getmaskarray(data).any(axis=0)
           & np.isfinite(data.data).all(axis=0))
    rgba=np.dstack((_rgb(data.filled(0),valid=valid),
                    valid.astype(np.uint8)*255))
    output = BytesIO()
    Image.fromarray(rgba,"RGBA").save(output, format="PNG")
    return output.getvalue()


def read_rgb_window(
    path: Path, longitude: float, latitude: float, window_size: int = 512,
) -> tuple[np.ndarray, int, int, object, str]:
    """Read at original pixels around a WGS84 click, not a rescaled preview."""
    if window_size < 32 or window_size > 1024:
        raise RasterError("Window size must be between 32 and 1024 pixels.")
    with rasterio.open(path) as src:
        _check(src)
        cx, cy = transform("EPSG:4326", src.crs, [longitude], [latitude])
        inverse = ~src.transform
        col_float, row_float = inverse @ (cx[0], cy[0])
        col, row = int(np.floor(col_float)), int(np.floor(row_float))
        if not (0 <= col < src.width and 0 <= row < src.height):
            raise RasterError("Clicked point is outside the georeferenced raster.")
        left = max(0, min(col - window_size // 2, src.width - window_size))
        top = max(0, min(row - window_size // 2, src.height - window_size))
        left, top = int(left), int(top)
        right, bottom = min(src.width, left + window_size), min(src.height, top + window_size)
        window = Window(left, top, right - left, bottom - top)
        indexes = [1, 2, 3] if src.count >= 3 else [1]
        pixels = src.read(indexes, window=window)
        return _rgb(pixels), col - left, row - top, src.window_transform(window), str(src.crs)
