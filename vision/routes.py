"""FastAPI endpoint for bounded automatic tracing of georeferenced images."""

import asyncio
import os
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from imagery.raster import RasterError
from imagery.store import image_file
from .sam import VisionUnavailable, sam_enabled
from .trace import trace_raster

router = APIRouter(prefix="/vision", tags=["vision"])
_limit = asyncio.Semaphore(1)


class TraceRequest(BaseModel):
    image_id: str
    longitude: float
    latitude: float
    method: Literal["color", "sam2"] = "color"
    tolerance: int = Field(default=20, ge=0, le=255)
    window_size: int = Field(default=512, ge=32, le=1024)


@router.get("/capabilities")
def vision_capabilities() -> dict:
    return {
        "color_trace": True,
        "color_native_acceleration": True,
        "sam2_configured": sam_enabled(),
        "sam2_model": os.getenv("GEOFATHOM_SAM2_MODEL_ID", "facebook/sam2.1-hiera-small"),
        "requires_georeferenced_raster": True,
        "note": "Color similarity is deterministic, not semantic object recognition. "
                "SAM 2 requires separate model installation and CUDA.",
    }


@router.post("/trace")
async def trace(body: TraceRequest) -> dict:
    try:
        path = image_file(body.image_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RasterError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if body.method == "sam2" and not sam_enabled():
        raise HTTPException(status_code=501, detail="SAM 2 is not enabled on the server.")
    async with _limit:
        try:
            return await run_in_threadpool(
                trace_raster, path, body.image_id,
                body.longitude, body.latitude,
                body.method, body.tolerance, body.window_size,
            )
        except VisionUnavailable as error:
            raise HTTPException(status_code=501, detail=str(error)) from error
        except (RasterError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
