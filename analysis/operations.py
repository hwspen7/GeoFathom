"""Validated spatial operators with explicit geodesic and projected units.

Overlay topology is evaluated on WGS84 coordinates for local geometries.
Metric buffers use a local azimuthal equidistant projection and are bounded
to avoid misleading world-scale analyses. Results retain provenance metadata.
"""

import math
from typing import Any, Literal

from pyproj import Geod, Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform
from shapely.validation import explain_validity

from geometry.measure import GeometryError, measure_geometry

_GEOD = Geod(ellps="WGS84")


def _valid(geometry: dict[str, Any], *, polygon: bool = False):
    measure_geometry(geometry)
    value = shape(geometry)
    if polygon and value.geom_type not in {"Polygon", "MultiPolygon"}:
        raise GeometryError("A polygon or multipolygon geometry is required.")
    if not value.is_valid:
        raise GeometryError(f"Invalid geometry: {explain_validity(value)}")
    bounds = value.bounds
    if bounds and (bounds[2] - bounds[0] > 170):
        raise GeometryError("Antimeridian-spanning geometries require specialized processing.")
    return value


def _serialize(geometry) -> dict | None:
    if geometry.is_empty:
        return None
    if geometry.geom_type not in {"Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point"}:
        raise GeometryError("The resulting geometry type is not supported.")
    return mapping(geometry)


def buffer_geometry(geometry: dict, distance_m: float, resolution: int = 16) -> dict:
    """Buffer local WGS84 shapes by meters using an azimuthal equidistant CRS."""
    if not math.isfinite(distance_m) or distance_m <= 0 or distance_m > 100_000:
        raise GeometryError("Buffer distance must be greater than zero and at most 100,000 meters.")
    if resolution < 4 or resolution > 64:
        raise GeometryError("Buffer resolution must be between 4 and 64.")
    original = _valid(geometry)
    center = original.centroid
    if abs(center.y) >= 85:
        raise GeometryError("Polar buffers need a dedicated projection workflow.")
    crs = (
        f"+proj=aeqd +lat_0={center.y:.9f} +lon_0={center.x:.9f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    to_local = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    to_world = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    output = transform(to_world, transform(to_local, original).buffer(distance_m, resolution))
    result = _serialize(output)
    if result is None:
        raise GeometryError("Buffer produced an empty geometry.")
    measurement = measure_geometry(result)
    return {
        "geometry": result,
        "measurement": measurement,
        "operation": "buffer",
        "distance_m": distance_m,
        "method": "Local azimuthal equidistant metric buffer; WGS84 output",
        "warning": "Local approximation. Not intended for legal setbacks or extreme latitudes.",
    }


def overlay_geometries(
    left: dict, right: dict, operation: Literal["intersection", "union", "difference"],
) -> dict:
    """Compute 2D overlays on polygonal WGS84 input geometries."""
    a = _valid(left, polygon=True)
    b = _valid(right, polygon=True)
    if abs(a.centroid.x - b.centroid.x) > 170:
        raise GeometryError("Cannot overlay polygons across the antimeridian.")
    if operation == "intersection":
        output = a.intersection(b)
    elif operation == "union":
        output = a.union(b)
    elif operation == "difference":
        output = a.difference(b)
    else:
        raise GeometryError("Unsupported overlay operation.")
    geometry = _serialize(output)
    return {
        "geometry": geometry,
        "measurement": measure_geometry(geometry) if geometry is not None else None,
        "empty": geometry is None,
        "operation": operation,
        "method": "Shapely planar topology on geographic WGS84 coordinates",
        "warning": "Overlay follows mapped boundaries, not verified legal parcel boundaries.",
    }


def compare_areas(left: dict, right: dict) -> dict:
    """Compare actual geodesic areas of two mapped polygon geometries."""
    _valid(left, polygon=True)
    _valid(right, polygon=True)
    a = measure_geometry(left)["area_m2"]
    b = measure_geometry(right)["area_m2"]
    return {
        "left_area_m2": a,
        "right_area_m2": b,
        "difference_m2": a - b,
        "ratio": a / b if b else None,
        "method": "WGS84 ellipsoidal geodesic area",
    }


def distance_between_points(first: list[float], second: list[float]) -> dict:
    """Measure ground distance and forward azimuth between two WGS84 points."""
    if len(first) != 2 or len(second) != 2:
        raise GeometryError("Two WGS84 longitude/latitude coordinate pairs are required.")
    if any(not math.isfinite(v) for v in first + second):
        raise GeometryError("All coordinates must be finite.")
    if any(not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in (first, second)):
        raise GeometryError("Coordinate values exceed WGS84 longitude/latitude bounds.")
    forward, _, meters = _GEOD.inv(first[0], first[1], second[0], second[1])
    return {
        "distance_m": meters,
        "distance_km": meters / 1000,
        "initial_bearing_deg": (forward + 360) % 360,
        "method": "WGS84 ellipsoidal inverse geodesic",
    }
