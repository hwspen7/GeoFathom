"""Compose independent geospatial, discovery and AI services."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from analysis.routes import router as analysis_router
from storage.routes import router as storage_router
from geometry.routes import router as geometry_router
from geometry.topology import native_available
from places.routes import router as places_router
from intelligence.routes import router as intelligence_router
from intelligence.llm import get_provider

settings = get_settings()
app = FastAPI(title="GeoFathom", description="Local-first geospatial intelligence")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-GeoFathom-Admin-Token"],
)
app.include_router(geometry_router)
app.include_router(places_router)
app.include_router(intelligence_router)
app.include_router(analysis_router)
app.include_router(storage_router)


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
        "llm_model": settings.llm_model,
        "llm_configured": get_provider(settings) is not None,
        "analysis_model": settings.analysis_model if settings.analysis_provider != "none" else None,
        "analysis_configured": get_provider(settings, "analysis") is not None,
        "vision_segmentation": False,
        "spatial_discovery": "bounded_osm",
        "imagery": "not configured",
        "native_geometry": native_available(),
        "persistent_projects": True,
        "spatial_analysis": ["buffer", "overlay", "compare", "distance"],
    }
