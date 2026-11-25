"""Bounded OSM feature discovery by area and category.

The public Overpass API is a constrained bootstrap provider, not a global
parcel index. A fixed request cap makes results explicitly non-exhaustive.
"""

import asyncio
import math
import time
from collections import OrderedDict
from typing import Any

import httpx

from core.config import Settings
from geometry.measure import GeometryError, measure_geometry

_FILTERS = {
    "building": '["building"]',
    "landuse": '["landuse"]',
    "water": '["natural"="water"]',
}
_CACHE: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_LOCK = asyncio.Lock()
_LAST_REQUEST = 0.0
_MAX_WAYS = 250
_MAX_RESULTS = 100


class DiscoveryError(ValueError):
    """Invalid or unbounded spatial query."""


def _validate_bounds(bbox: tuple[float, float, float, float]) -> None:
    west, south, east, north = bbox
    if not all(math.isfinite(value) for value in bbox):
        raise DiscoveryError("Bounding coordinates must be finite.")
    if (
        west < -180 or east > 180 or south < -90 or north > 90
        or east <= west or north <= south
    ):
        raise DiscoveryError("Use a valid bounding box in west, south, east, north order.")
    if (east - west) > 0.055 or (north - south) > 0.055:
        raise DiscoveryError("Zoom in to a neighborhood (about 5 km across) before searching.")


def _from_way(element: dict[str, Any], category: str) -> dict[str, Any] | None:
    if element.get("type") != "way" or not isinstance(element.get("geometry"), list):
        return None
    positions = [
        [point["lon"], point["lat"]]
        for point in element["geometry"]
        if "lon" in point and "lat" in point
    ]
    if len(positions) < 4 or positions[0] != positions[-1]:
        return None
    geometry = {"type": "Polygon", "coordinates": [positions]}
    try:
        measurement = measure_geometry(geometry)
    except GeometryError:
        return None
    west, south, east, north = measurement["bounds"]
    tags = element.get("tags") or {}
    identifier = element.get("id")
    label = str(tags.get("name") or f"{category.capitalize()} OSM {identifier}")
    return {
        "id": f"osm:way:{identifier}",
        "name": label,
        "display_name": str(tags.get("name") or tags.get(category) or category.capitalize()),
        "longitude": (west + east) / 2,
        "latitude": (south + north) / 2,
        "bbox": [west, south, east, north],
        "geometry": geometry,
        "boundary_status": "mapped",
        "source": "OpenStreetMap via Overpass",
        "osm_type": "way",
        "osm_id": identifier,
        "measurement": measurement,
    }


async def _query_overpass(
    bbox: tuple[float, float, float, float], category: str, settings: Settings,
) -> list[dict[str, Any]]:
    global _LAST_REQUEST
    key = f"{settings.overpass_url}|{category}|{','.join(f'{v:.6f}' for v in bbox)}"
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 900:
        return cached[1]
    async with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1]
        delay = max(0.0, 2.0 - (time.monotonic() - _LAST_REQUEST))
        if delay:
            await asyncio.sleep(delay)
        west, south, east, north = bbox
        overpass_query = (
            f"[out:json][timeout:20];"
            f"way{_FILTERS[category]}"
            f"({south:.6f},{west:.6f},{north:.6f},{east:.6f});"
            f"out geom {_MAX_WAYS};"
        )
        _LAST_REQUEST = time.monotonic()
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(
                settings.overpass_url,
                data={"data": overpass_query},
                headers={"User-Agent": "GeoFathom-geospatial-workspace"},
            )
            response.raise_for_status()
            payload = response.json()
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise ValueError("Invalid Overpass response.")
        _CACHE[key] = (time.monotonic(), elements)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 64:
            _CACHE.popitem(last=False)
        return elements


async def discover_features(
    bbox: tuple[float, float, float, float],
    category: str,
    minimum_area_m2: float,
    maximum_area_m2: float | None,
    settings: Settings,
) -> dict[str, Any]:
    if category not in _FILTERS:
        raise DiscoveryError("Unsupported feature category.")
    _validate_bounds(bbox)
    if not math.isfinite(minimum_area_m2) or minimum_area_m2 < 0:
        raise DiscoveryError("Minimum area must be finite and nonnegative.")
    if maximum_area_m2 is not None and (
        not math.isfinite(maximum_area_m2) or maximum_area_m2 < minimum_area_m2
    ):
        raise DiscoveryError("Maximum area must be finite and not below minimum area.")
    elements = await _query_overpass(bbox, category, settings)
    results = []
    for element in elements:
        item = _from_way(element, category)
        if not item:
            continue
        area = item["measurement"]["area_m2"]
        if area >= minimum_area_m2 and (maximum_area_m2 is None or area <= maximum_area_m2):
            results.append(item)
    results.sort(key=lambda item: item["measurement"]["area_m2"], reverse=True)
    truncated = len(elements) >= _MAX_WAYS or len(results) > _MAX_RESULTS
    return {
        "results": results[:_MAX_RESULTS],
        "checked": len(elements),
        "truncated": truncated,
        "warning": (
            "Non-exhaustive OSM way search. Relation geometries, unmapped features, "
            "and results beyond provider limits are not included."
        ),
        "category": category,
        "source": "OpenStreetMap via Overpass",
    }
