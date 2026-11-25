"""Compose independent geospatial, discovery and AI services."""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .security import APIBoundaryMiddleware
from .health import router as health_router
from analysis.routes import router as analysis_router
from analysis.pro_routes import router as spatial_workflow_router
from analysis.classification_routes import router as classification_router, project_router as graduated_project_router
from storage.crs_routes import router as crs_router
from storage.postgis_routes import router as postgis_router
from services.routes import router as ogc_router
from jobs.routes import router as jobs_router
from cartography.routes import router as print_router
from storage.routes import router as storage_router
from storage.workspace_routes import router as workspace_router
from storage.topology_routes import router as topology_router
from storage.attribute_routes import router as attribute_router
from storage.cartography_routes import router as cartography_router
from storage.vector_routes import router as vector_router
from imagery.routes import router as imagery_router
from terrain.routes import router as terrain_router
from terrain.resource_routes import router as terrain_resource_router
from vision.routes import router as vision_router
from geometry.routes import router as geometry_router
from geometry.edit_routes import router as edit_router
from geometry.topology import native_available
from places.routes import router as places_router
from intelligence.routes import router as intelligence_router
from intelligence.llm import get_provider

settings = get_settings()
app = FastAPI(title="GeoFathom", description="Local-first geospatial intelligence")
# Add auth before CORS so CORS remains the outer middleware and browser
# clients can receive correctly labeled access-denied responses.
app.add_middleware(APIBoundaryMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-GeoFathom-API-Key",
                   "X-GeoFathom-Admin-Token", "X-GeoFathom-Local-Import"],
)
app.include_router(health_router)
app.include_router(geometry_router)
app.include_router(edit_router)
app.include_router(places_router)
app.include_router(intelligence_router)
app.include_router(analysis_router)
app.include_router(spatial_workflow_router)
app.include_router(classification_router)
app.include_router(graduated_project_router)
app.include_router(crs_router)
app.include_router(postgis_router)
app.include_router(ogc_router)
app.include_router(jobs_router)
app.include_router(print_router)
app.include_router(storage_router)
app.include_router(workspace_router)
app.include_router(topology_router)
app.include_router(attribute_router)
app.include_router(cartography_router)
app.include_router(vector_router)
app.include_router(imagery_router)
app.include_router(terrain_router)
app.include_router(terrain_resource_router)
app.include_router(vision_router)


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
        "vision_segmentation": True,
        "vision_methods": ["color", "sam2_optional"],
        "georeferenced_imagery": True,
        "local_raster_import": os.getenv("GEOFATHOM_AUTH_MODE","local").lower()=="local"
            and not os.getenv("GEOFATHOM_MODEL_ADMIN_TOKEN"),
        "spatial_discovery": "bounded_osm",
        "imagery": "local_geotiff_and_public_stac_metadata",
        "native_geometry": native_available(),
        "persistent_projects": True,
        "spatial_analysis": ["buffer", "overlay", "compare", "distance"],
    }
