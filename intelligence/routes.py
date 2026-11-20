"""FastAPI AI execution, task traces and unconfigured vision adapters."""

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from core.config import get_settings
from .agent import execute
from .llm import get_provider
from .catalog import (CatalogError, ModelSpec, list_public, model_spec,
                      provider_for_spec, require_admin, remove_spec, save_spec,
                      select_default)

router = APIRouter(tags=["intelligence"])
logger = logging.getLogger("geofathom.intelligence")
settings = get_settings()


class AssistantRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)
    bbox: tuple[float, float, float, float] | None = None
    profile: Literal['default', 'analysis'] = 'default'
    model_id: str | None = Field(default=None, max_length=63)


@router.post("/assistant")
async def assistant(body: AssistantRequest) -> dict:
    try:
        return await execute(body.message, settings, body.bbox, body.profile, body.model_id)
    except CatalogError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
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
        "note": "Configured means an API key or local endpoint is set; use POST /models/probe for a live request. Keys are never returned.",
    }


def get_model(profile: Literal["default", "analysis"]) -> bool:
    return get_provider(settings, profile) is not None


class ProbeRequest(BaseModel):
    profile: Literal["default", "analysis"] = "default"
    model_id: str | None = Field(default=None, max_length=63)


@router.post("/models/probe")
async def probe_model(body: ProbeRequest) -> dict:
    """Perform a real, low-token model call without invoking any geographic data service."""
    try:
        spec = model_spec(body.model_id) if body.model_id else None
    except CatalogError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    provider = provider_for_spec(spec, settings) if spec else get_provider(settings, body.profile)
    if provider is None:
        raise HTTPException(
            status_code=409,
            detail="Model is not configured. Add its API key to the server-side .env file.",
        )
    try:
        parsed = await provider.parse("Locate Shanghai Hongqiao International Airport.")
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (401, 403):
            message = "API credentials were rejected or this model is not accessible."
        elif status == 429:
            message = "Provider free-tier quota or rate limit was reached."
        else:
            message = "Model provider returned an error."
        raise HTTPException(status_code=429 if status == 429 else 502, detail=message) from error
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        logger.warning("Model probe failed: %s", type(error).__name__)
        raise HTTPException(status_code=502, detail="Could not obtain a valid model response.") from error
    return {
        "status": "ready",
        "profile": body.profile,
        "model": spec.model if spec else (
            settings.llm_model if body.profile == "default" else settings.analysis_model
        ),
        "provider": spec.provider if spec else (
            settings.llm_provider if body.profile == "default" else settings.analysis_provider
        ),
        "model_id": spec.id if spec else None,
        "intent": parsed,
        "live_call": True,
    }





@router.get("/models/catalog")
def model_catalog() -> dict:
    """List built-in presets and user-created models without revealing credentials."""
    try:
        return list_public(settings)
    except CatalogError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _admin(token: str | None) -> None:
    try:
        require_admin(token)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.put("/models/catalog/{model_id}")
def upsert_model(
    model_id: str, body: ModelSpec,
    token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token"),
) -> dict:
    _admin(token)
    if model_id != body.id:
        raise HTTPException(status_code=422, detail="Path model ID does not match the configuration.")
    try:
        save_spec(body)
        return list_public(settings)
    except CatalogError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/models/catalog/{model_id}")
def delete_model(
    model_id: str,
    token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token"),
) -> dict:
    _admin(token)
    try:
        remove_spec(model_id)
        return list_public(settings)
    except CatalogError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class DefaultModelRequest(BaseModel):
    model_id: str = Field(min_length=2, max_length=63)


@router.put("/models/selection")
def change_default(
    body: DefaultModelRequest,
    token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token"),
) -> dict:
    _admin(token)
    try:
        select_default(body.model_id)
        return list_public(settings)
    except CatalogError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


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
