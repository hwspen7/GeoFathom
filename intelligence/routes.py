"""AI intent orchestration, with explicit unavailable vision capabilities."""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import get_settings
from geometry.measure import GeometryError, measure_geometry
from places.geocoding import search_places
from .intent import fallback_intent
from .llm import get_provider

router = APIRouter(tags=["intelligence"])
logger = logging.getLogger("geofathom.intelligence")
settings = get_settings()


class AssistantRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)


@router.post("/assistant")
async def assistant(body: AssistantRequest) -> dict:
    provider = get_provider(settings)
    intent = fallback_intent(body.message)
    model_used = False
    if provider:
        try:
            prediction = await provider.parse(body.message)
            if prediction["query"]:
                intent = prediction
                model_used = True
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            logger.warning("Model unavailable; using rule-based interpretation: %s", error)

    if intent["action"] == "discover":
        return {
            "status": "not_supported",
            "message": (
                "Natural-language spatial filtering is not yet wired to a feature index. "
                "Use the bounded area-search panel. No results have been fabricated."
            ),
            "intent": intent,
            "model_used": model_used,
            "results": [],
            "measurement": None,
        }

    try:
        candidates = await search_places(intent["query"], settings)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Geocoder unavailable: %s", error)
        raise HTTPException(
            status_code=503, detail="Geocoding provider unavailable. Try again later."
        ) from error

    if not candidates:
        return {
            "status": "not_found",
            "message": "No reliable match. Try another name or draw directly on the map.",
            "intent": intent,
            "model_used": model_used,
            "results": [],
            "measurement": None,
        }

    boundary = candidates[0].get("geometry")
    measurement = None
    if boundary:
        try:
            measurement = measure_geometry(boundary)
        except GeometryError:
            boundary = None

    message = (
        "Found mapped geometry. Check that it represents your intended boundary."
        if boundary else
        "Location found without a usable mapped boundary. Draw a polygon to measure."
    )
    return {
        "status": "matched" if len(candidates) == 1 else "candidates",
        "message": message,
        "intent": intent,
        "model_used": model_used,
        "results": candidates,
        "measurement": measurement,
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
