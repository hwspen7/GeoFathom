"""Optional C++ topology acceleration with a Shapely reference fallback.

Native kernels perform local containment, not geodesic area calculation.
Shapes with holes or antimeridian-crossing coordinates use Shapely.
"""

import ctypes
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import Point, shape

from .measure import GeometryError

_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _native() -> ctypes.CDLL | None:
    extension = ".dll" if sys.platform == "win32" else (
        ".dylib" if sys.platform == "darwin" else ".so"
    )
    filename = ("geofathom_native" if sys.platform == "win32"
                else "libgeofathom_native") + extension
    override = os.getenv("GEOFATHOM_NATIVE_LIBRARY", "")
    candidates = [
        Path(override) if override else None,
        _ROOT / "build" / "native" / filename,
        _ROOT / "build" / "native" / "Release" / filename,
        Path(__file__).resolve().parent / "native" / filename,
    ]
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        try:
            library = ctypes.CDLL(str(candidate))
            library.gf_contains_ring.argtypes = [
                ctypes.POINTER(ctypes.c_double),
                ctypes.c_size_t,
                ctypes.c_double,
                ctypes.c_double,
            ]
            library.gf_contains_ring.restype = ctypes.c_int
            library.gf_bbox_overlaps.argtypes = [
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
            ]
            library.gf_bbox_overlaps.restype = ctypes.c_int
            return library
        except (OSError, AttributeError):
            continue
    return None


def native_available() -> bool:
    """Return whether the optional compiled geometry library was loaded."""
    return _native() is not None


def contains_point(geometry: dict[str, Any], longitude: float, latitude: float) -> bool:
    """Test containment for GeoJSON polygons; exclude boundary points."""
    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "Polygon", "MultiPolygon"
    }:
        raise GeometryError("Point containment requires Polygon or MultiPolygon geometry.")
    if (not math.isfinite(longitude) or not math.isfinite(latitude)
            or not (-180 <= longitude <= 180 and -90 <= latitude <= 90)):
        raise GeometryError("Point coordinates must be finite WGS84 degrees.")

    try:
        polygon = shape(geometry)
    except (KeyError, ValueError, TypeError) as error:
        raise GeometryError("Invalid GeoJSON geometry.") from error
    if polygon.is_empty or not polygon.is_valid:
        raise GeometryError("Invalid polygon topology.")

    coordinates = geometry["coordinates"]
    native = _native()
    if (
        native is not None and geometry["type"] == "Polygon"
        and len(coordinates) == 1 and polygon.bounds[2] - polygon.bounds[0] < 180
    ):
        ring = coordinates[0]
        values = [float(value) for position in ring for value in position[:2]]
        buffer = (ctypes.c_double * len(values))(*values)
        return bool(native.gf_contains_ring(buffer, len(ring), longitude, latitude))

    return bool(polygon.contains(Point(longitude, latitude)))


def bbox_overlaps(first: list[float], second: list[float]) -> bool:
    """Compute a basic axis-aligned overlap; no antimeridian wrapping."""
    if len(first) != 4 or len(second) != 4:
        raise GeometryError("Each bounding box needs west, south, east, north.")
    if not all(math.isfinite(v) for v in first + second):
        raise GeometryError("Bounding boxes require finite values.")
    if first[0] > first[2] or first[1] > first[3] or second[0] > second[2] or second[1] > second[3]:
        raise GeometryError("Bounding box must have ordered coordinates.")
    native = _native()
    if native is not None:
        a = (ctypes.c_double * 4)(*first)
        b = (ctypes.c_double * 4)(*second)
        return bool(native.gf_bbox_overlaps(a, b))
    return (
        first[0] <= second[2] and second[0] <= first[2]
        and first[1] <= second[3] and second[1] <= first[3]
    )
