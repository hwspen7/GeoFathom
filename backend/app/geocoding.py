"""OpenStreetMap Nominatim search, with provenance, cache and a request throttle."""

import asyncio
import time
from collections import OrderedDict
from typing import Any

import httpx

from .config import Settings

_cache: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_lock = asyncio.Lock()
_last_request = 0.0


def _place(item: dict[str, Any]) -> dict[str, Any]:
    bbox = item.get("boundingbox") or []
    bounds = None
    if len(bbox) == 4:
        # Nominatim returns south, north, west, east.
        bounds = [float(bbox[2]), float(bbox[0]), float(bbox[3]), float(bbox[1])]
    geometry = item.get("geojson")
    usable = isinstance(geometry, dict) and geometry.get("type") in {
        "Polygon", "MultiPolygon", "LineString", "MultiLineString"
    }
    return {
        "id": f"osm:{item.get('osm_type', 'unknown')}:{item.get('osm_id', 'unknown')}",
        "name": item.get("name") or item.get("display_name", "").split(",")[0],
        "display_name": item.get("display_name", ""),
        "longitude": float(item["lon"]),
        "latitude": float(item["lat"]),
        "bbox": bounds,
        "geometry": geometry if usable else None,
        "boundary_status": "mapped" if usable else "location_only",
        "source": "OpenStreetMap via Nominatim",
        "osm_type": item.get("osm_type"),
        "osm_id": item.get("osm_id"),
    }


async def search_places(query: str, settings: Settings, limit: int = 5) -> list[dict[str, Any]]:
    """Limit uncached requests to one per second in a single service process."""
    global _last_request
    key = f"{settings.nominatim_url}|{query.strip().casefold()}|{limit}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < 3600:
        return cached[1]
    async with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 3600:
            return cached[1]
        delay = max(0.0, 1.05 - (time.monotonic() - _last_request))
        if delay:
            await asyncio.sleep(delay)
        headers = {
            "User-Agent": (
                f"GeoFathom-geospatial-workspace ({settings.contact_email})"
                if settings.contact_email else "GeoFathom-local-development (set GEOFATHOM_CONTACT_EMAIL)"
            ),
            "Accept": "application/json",
        }
        _last_request = time.monotonic()
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                f"{settings.nominatim_url}/search",
                params={"q": query, "format": "jsonv2", "polygon_geojson": 1, "limit": limit},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected geocoding response.")
        places = [_place(record) for record in data if isinstance(record, dict)]
        _cache[key] = (time.monotonic(), places)
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
        return places
