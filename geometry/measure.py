"""Ellipsoidal WGS84 measurements from user-supplied or sourced GeoJSON."""

import math
from typing import Any

from pyproj import Geod
from shapely.geometry import shape
from shapely.errors import GEOSException
from shapely.validation import explain_validity

_GEOD = Geod(ellps="WGS84")
_ALLOWED = {"Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point", "MultiPoint"}
_MAX_POINTS = 20_000


class GeometryError(ValueError):
    """An invalid or unsupported geographic geometry."""


def _check_coordinates(value: Any, kind: str) -> int:
    """Validate fixed GeoJSON nesting before allocating native geometry."""
    count = 0
    dimension = None

    def array(node, minimum):
        if not isinstance(node, (list, tuple)) or len(node) < minimum:
            raise GeometryError("Invalid GeoJSON coordinate structure.")
        return node

    def position(node):
        nonlocal count, dimension
        array(node, 2)
        if len(node) not in (2, 3):
            raise GeometryError("Coordinate positions must have two or three ordinates.")
        if dimension is None:
            dimension = len(node)
        if len(node) != dimension:
            raise GeometryError("Coordinate positions must have consistent dimensions.")
        for v in node:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise GeometryError("Coordinates must be finite WGS84 longitude/latitude pairs.")
            try:
                finite = math.isfinite(v)
            except OverflowError:
                finite = False
            if not finite:
                raise GeometryError("Coordinates must be finite WGS84 longitude/latitude pairs.")
        if not (-180 <= node[0] <= 180 and -90 <= node[1] <= 90):
            raise GeometryError("Coordinates must be finite WGS84 longitude/latitude pairs.")
        count += 1
        if count > _MAX_POINTS:
            raise GeometryError("Geometry must contain between 1 and 20,000 coordinates.")

    def line(node, ring=False):
        array(node, 4 if ring else 2)
        for pos in node:
            position(pos)
        if ring and tuple(node[0]) != tuple(node[-1]):
            raise GeometryError("GeoJSON polygon rings must be closed.")

    def polygon(node):
        for ring in array(node, 1):
            line(ring, ring=True)

    if kind == "Point":
        position(value)
    elif kind == "MultiPoint":
        for point in array(value, 1):position(point)
    elif kind == "LineString":
        line(value)
    elif kind == "MultiLineString":
        for item in array(value, 1):
            line(item)
    elif kind == "Polygon":
        polygon(value)
    else:
        for item in array(value, 1):
            polygon(item)
    return count


def measure_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Measure GeoJSON on the ellipsoid, rather than in screen pixels."""
    if not isinstance(geometry, dict):
        raise GeometryError("A GeoJSON geometry object is required.")
    kind = geometry.get("type")
    if not isinstance(kind, str) or kind not in _ALLOWED:
        raise GeometryError("Supported types: Polygon, MultiPolygon, LineString, MultiLineString, Point, MultiPoint.")
    points = _check_coordinates(geometry.get("coordinates"), kind)
    if points == 0 or points > _MAX_POINTS:
        raise GeometryError("Geometry must contain between 1 and 20,000 coordinates.")

    try:
        item = shape(geometry)
    except (TypeError, ValueError, KeyError, IndexError, OverflowError, GEOSException) as error:
        raise GeometryError("Invalid GeoJSON coordinates.") from error
    if item.is_empty or not item.is_valid:
        raise GeometryError(f"Invalid geometry: {explain_validity(item)}")

    area = perimeter = length = None
    if kind in {"Polygon", "MultiPolygon"}:
        # GeoJSON producers do not always follow right-hand ring ordering.
        # Compute each boundary independently: holes subtract, independent
        # polygon components add, and all boundary lengths contribute.
        polygons = [item] if kind == "Polygon" else list(item.geoms)
        areas, lengths = [], []
        for polygon in polygons:
            exterior_area, exterior_length = _GEOD.polygon_area_perimeter(
                *zip(*(p[:2] for p in polygon.exterior.coords)))
            holes = [_GEOD.polygon_area_perimeter(
                *zip(*(p[:2] for p in ring.coords))) for ring in polygon.interiors]
            component = abs(exterior_area) - math.fsum(abs(a) for a, _ in holes)
            if not math.isfinite(component) or component <= 0:
                raise GeometryError("Polygon has no positive local ellipsoidal area.")
            areas.append(component)
            lengths.extend([exterior_length, *(length for _, length in holes)])
        area, perimeter = math.fsum(areas), math.fsum(lengths)
    elif kind in {"LineString", "MultiLineString"}:
        length = _GEOD.geometry_length(item)

    if any(v is not None and not math.isfinite(v) for v in (area, perimeter, length)):
        raise GeometryError("Geometry measurement is outside the supported numerical domain.")

    # Bounded edge measurements for on-map dimension labels. The ordering
    # matches GeoJSON parts/rings, including closing edges and holes.
    if kind in {"Polygon", "MultiPolygon"}:
        boundaries = [ring.coords for polygon in polygons for ring in
                      (polygon.exterior, *polygon.interiors)]
    elif kind == "LineString":
        boundaries = [item.coords]
    elif kind == "MultiLineString":
        boundaries = [line.coords for line in item.geoms]
    else:
        boundaries = []
    segments = []
    for boundary in boundaries:
        for i in range(min(len(boundary)-1, 48-len(segments))):
            segments.append((boundary[i], boundary[i+1]))
        if len(segments) == 48:
            break
    edges = []
    if segments:
        _, _, distances = _GEOD.inv(
            [a[0] for a,b in segments], [a[1] for a,b in segments],
            [b[0] for a,b in segments], [b[1] for a,b in segments])
        edges = [float(distance) for distance in distances]
    return {
        "geometry_type": kind,
        "edge_lengths_m": edges,
        "area_m2": area,
        "area_km2": area / 1_000_000 if area is not None else None,
        "perimeter_m": perimeter,
        "length_m": length,
        "bounds": list(item.bounds),
        "coordinate_count": points,
        "method": "WGS84 ellipsoidal geodesic",
        "note": "A geometric measurement, not a verified legal land parcel. Polygon perimeter includes exterior and hole boundaries.",
    }
