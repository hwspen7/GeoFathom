"""Ellipsoidal WGS84 measurements from user-supplied or sourced GeoJSON."""

import math
from typing import Any

from pyproj import Geod
from shapely.geometry import shape
from shapely.validation import explain_validity

_GEOD = Geod(ellps="WGS84")
_ALLOWED = {"Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point"}
_MAX_POINTS = 20_000


class GeometryError(ValueError):
    """An invalid or unsupported geographic geometry."""


def _check_coordinates(value: Any) -> int:
    if not isinstance(value, (list, tuple)):
        raise GeometryError("Coordinates must be arrays.")
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        lon, lat = value[:2]
        if (
            isinstance(lon, bool)
            or isinstance(lat, bool)
            or not math.isfinite(lon)
            or not math.isfinite(lat)
            or not (-180 <= lon <= 180 and -90 <= lat <= 90)
        ):
            raise GeometryError("Coordinates must be finite WGS84 longitude/latitude pairs.")
        return 1
    return sum(_check_coordinates(part) for part in value)


def measure_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Measure GeoJSON on the ellipsoid, rather than in screen pixels."""
    if not isinstance(geometry, dict):
        raise GeometryError("A GeoJSON geometry object is required.")
    kind = geometry.get("type")
    if kind not in _ALLOWED:
        raise GeometryError("Supported types: Polygon, MultiPolygon, LineString, MultiLineString, Point.")
    points = _check_coordinates(geometry.get("coordinates"))
    if points == 0 or points > _MAX_POINTS:
        raise GeometryError("Geometry must contain between 1 and 20,000 coordinates.")

    try:
        item = shape(geometry)
    except (TypeError, ValueError, KeyError) as error:
        raise GeometryError("Invalid GeoJSON coordinates.") from error
    if item.is_empty or not item.is_valid:
        raise GeometryError(f"Invalid geometry: {explain_validity(item)}")

    area = perimeter = length = None
    if kind in {"Polygon", "MultiPolygon"}:
        signed_area, perimeter = _GEOD.geometry_area_perimeter(item)
        area = abs(signed_area)
    elif kind in {"LineString", "MultiLineString"}:
        length = _GEOD.geometry_length(item)

    return {
        "geometry_type": kind,
        "area_m2": area,
        "area_km2": area / 1_000_000 if area is not None else None,
        "perimeter_m": perimeter,
        "length_m": length,
        "bounds": list(item.bounds),
        "coordinate_count": points,
        "method": "WGS84 ellipsoidal geodesic",
        "note": "A geometric measurement, not a verified legal land parcel.",
    }
