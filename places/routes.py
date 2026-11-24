"""Place lookup and bounded OSM feature-discovery endpoints."""

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.config import get_settings
from .geocoding import search_places
from .discovery import DiscoveryError, discover_features

router = APIRouter(tags=["places"])
logger = logging.getLogger("geofathom.places")
settings = get_settings()


class DiscoverRequest(BaseModel):
    bbox: tuple[float, float, float, float]
    category: Literal["building", "landuse", "water"] = "building"
    minimum_area_m2: float = Field(default=0, ge=0)
    maximum_area_m2: float | None = Field(default=None, ge=0)


@router.get("/search")
async def search(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(5, ge=1, le=8),
) -> dict:
    try:
        return {"results": await search_places(q, settings, limit)}
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Geocoder unavailable: %s", error)
        raise HTTPException(
            status_code=503, detail="Geocoding provider unavailable. Try again later."
        ) from error


@router.post("/discover")
async def discover(body: DiscoverRequest) -> dict:
    """Find mapped OSM polygon ways within a constrained map viewport."""
    try:
        return await discover_features(
            body.bbox,
            body.category,
            body.minimum_area_m2,
            body.maximum_area_m2,
            settings,
        )
    except DiscoveryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Spatial discovery provider failed: %s", error)
        raise HTTPException(
            status_code=503, detail="Spatial discovery provider unavailable. Try again later."
        ) from error
