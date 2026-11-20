"""FastAPI AI execution, task traces and unconfigured vision adapters."""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import get_settings
from .agent import execute

router = APIRouter(tags=["intelligence"])
logger = logging.getLogger("geofathom.intelligence")
settings = get_settings()


class AssistantRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)
    bbox: tuple[float, float, float, float] | None = None


@router.post("/assistant")
async def assistant(body: AssistantRequest) -> dict:
    try:
        return await execute(body.message, settings, body.bbox)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Geo search provider unavailable: %s", error)
        raise HTTPException(
            status_code=503,
            detail="The geographic search provider is unavailable. Retry later.",
        ) from error


@router.get("/assistant/tools")
def available_tools() -> dict:
    return {
        "tools": [
            {"name": "search_places", "capability": "named_place_lookup", "ready": True},
            {"name": "measure_geometry", "capability": "geodesic_measurement", "ready": True},
            {"name": "discover_features", "capability": "bounded_area_search", "ready": True},
            {"name": "spatial_analysis", "capability": "buffer_overlay_compare", "ready": True},
            {"name": "satellite_segmentation", "capability": "vision", "ready": False},
        ],
        "safety": "Coordinates and geographic measurements always come from tools, not the model.",
    }


@router.post("/vision/segment", status_code=501)
def segment_unavailable() -> dict:
    raise HTTPException(
        status_code=501,
        detail=(
            "Satellite segmentation is not configured. "
            "An authorized georeferenced imagery source and vision provider are required."
        ),
    )
