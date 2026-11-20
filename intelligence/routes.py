"""FastAPI AI execution, task traces and unconfigured vision adapters."""

import logging
from typing import Literal

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
    profile: Literal['default', 'analysis'] = 'default'


@router.post("/assistant")
async def assistant(body: AssistantRequest) -> dict:
    try:
        return await execute(body.message, settings, body.bbox, body.profile)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Geo search provider unavailable: %s", error)
        raise HTTPException(
            status_code=503,
            detail="The geographic search provider is unavailable. Retry later.",
        ) from error


@router.get("/models")
def models() -> dict:
    return {
        "default": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "configured": get_model("default"),
        },
        "analysis": {
            "provider": settings.analysis_provider,
            "model": settings.analysis_model or None,
            "configured": get_model("analysis"),
        },
        "note": "Configured does not mean running. Model weights are not shipped by GeoFathom.",
    }


def get_model(profile: Literal["default", "analysis"]) -> bool:
    from .llm import get_provider
    return get_provider(settings, profile) is not None


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
