"""API for discovery, geodesic measurement, and optional language-model routing."""

import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import get_settings
from .geo import GeometryError, measure_geometry
from .geocoding import search_places
from .intent import fallback_intent
from .llm import get_provider

logger = logging.getLogger("geofathom")
settings = get_settings()
app = FastAPI(title="GeoFathom", description="Local-first geospatial analysis platform")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class MeasureRequest(BaseModel):
    geometry: dict[str, Any]


class AssistantRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "GeoFathom"}


@app.get("/capabilities")
def capabilities() -> dict:
    return {
        "geocoding": "nominatim",
        "geodesic_measurement": True,
        "geojson_export": True,
        "llm_provider": settings.llm_provider if get_provider(settings) else None,
        "vision_segmentation": False,
        "spatial_discovery": False,
        "imagery": "not configured",
    }


@app.get("/search")
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


@app.post("/measure")
def measure(body: MeasureRequest) -> dict:
    try:
        return measure_geometry(body.geometry)
    except GeometryError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/assistant")
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
            logger.warning("Model failed; using rule-based parsing: %s", error)

    if intent["action"] == "discover":
        return {
            "status": "not_supported",
            "message": (
                "Spatial feature discovery requires a configured feature index. "
                "No candidates or areas have been fabricated."
            ),
            "intent": intent, "model_used": model_used, "results": [],
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
            "message": "No reliable location match. Try another name or draw on the map.",
            "intent": intent, "model_used": model_used, "results": [],
            "measurement": None,
        }

    primary = candidates[0]
    geometry = primary.get("geometry")
    measurement = None
    if geometry:
        try:
            measurement = measure_geometry(geometry)
        except GeometryError:
            geometry = None

    message = (
        "Found mapped geometry. Confirm it represents your intended measurement boundary."
        if geometry else
        "Location found, but no usable mapped boundary exists. Draw one to measure."
    )
    return {
        "status": "matched" if len(candidates) == 1 else "candidates",
        "message": message,
        "intent": intent, "model_used": model_used, "results": candidates,
        "measurement": measurement,
    }


@app.post("/vision/segment", status_code=501)
def segment_unavailable() -> dict:
    raise HTTPException(
        status_code=501,
        detail=(
            "Satellite image segmentation is not configured. "
            "An authorized imagery source and vision provider are required."
        ),
    )
