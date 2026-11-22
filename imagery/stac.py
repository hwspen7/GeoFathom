"""Public STAC metadata discovery, distinct from raster download or inference.

Only a fixed server-side public catalog is queried. No caller-controlled URL
is fetched, preventing the endpoint from acting as an arbitrary HTTP proxy.
"""

from datetime import date
import math

import httpx

STAC_API = "https://earth-search.aws.element84.com/v1/search"
_COLLECTIONS = {"sentinel-2-l2a", "sentinel-2-l1c", "sentinel-1-grd"}


class CatalogSearchError(ValueError):
    """Unsupported or unbounded STAC search."""


def _bounds(bounds: tuple[float, float, float, float]) -> list[float]:
    west, south, east, north = bounds
    if (
        not all(math.isfinite(x) for x in bounds)
        or not (-180 <= west < east <= 180 and -90 <= south < north <= 90)
    ):
        raise CatalogSearchError("Search needs valid WGS84 west/south/east/north bounds.")
    if east - west > 3 or north - south > 3:
        raise CatalogSearchError("Zoom into a region of at most 3 degrees in each dimension.")
    return list(bounds)


async def search_stac(
    bbox: tuple[float, float, float, float],
    collection: str = "sentinel-2-l2a",
    limit: int = 8,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if collection not in _COLLECTIONS:
        raise CatalogSearchError("Unsupported public imagery collection.")
    if not 1 <= limit <= 12:
        raise CatalogSearchError("Search limit must be between 1 and 12.")
    if start_date and end_date and end_date < start_date:
        raise CatalogSearchError("End date must be after the start date.")
    payload = {"collections": [collection], "bbox": _bounds(bbox), "limit": limit}
    if start_date or end_date:
        begin = start_date.isoformat() if start_date else ".."
        end = end_date.isoformat() if end_date else ".."
        payload["datetime"] = f"{begin}/{end}"
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        response = await client.post(
            STAC_API,
            json=payload,
            headers={"Accept": "application/geo+json",
                     "User-Agent": "GeoFathom-public-STAC-metadata-search"},
        )
        response.raise_for_status()
        data = response.json()
    if (not isinstance(data, dict) or data.get("type") != "FeatureCollection"
            or not isinstance(data.get("features"), list)):
        raise ValueError("Catalog returned an invalid STAC feature collection.")
    items = []
    for feature in data["features"][:limit]:
        if not isinstance(feature, dict):
            continue
        # A provider may return malformed optional metadata. Do not turn
        # that into an unhandled 500 or expose non-HTTPS catalog URLs.
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        links = feature.get("links")
        if not isinstance(links, list):
            links = []
        href = next(
            (link["href"] for link in links
             if isinstance(link, dict) and link.get("rel") == "self"
             and isinstance(link.get("href"), str)
             and link["href"].startswith("https://")),
            None,
        )
        items.append({
            "id": str(feature.get("id", ""))[:250],
            "collection": str(feature.get("collection", collection))[:100],
            "datetime": properties.get("datetime"),
            "cloud_cover": properties.get("eo:cloud_cover"),
            "bbox": feature.get("bbox"),
            "catalog_url": href,
            "source": "Element 84 Earth Search public STAC metadata",
        })
    return {
        "items": items,
        "count": len(items),
        "collection": collection,
        "warning": "Catalog metadata only. This does not download imagery, grant usage rights, "
                   "or guarantee the resolution needed for object outlines.",
    }
