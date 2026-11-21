"""Local GeoTIFF ingest and georeferenced preview endpoints."""

import os
from datetime import date
import tempfile

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
import httpx
from pydantic import BaseModel, Field
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from intelligence.catalog import require_admin
from .raster import RasterError
from .cache import cached_preview
from .stac import CatalogSearchError, search_stac
from .store import describe, image_file, imagery_dir, list_images, store_upload

router = APIRouter(prefix="/imagery", tags=["imagery"])
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


@router.get("")
def images() -> dict:
    return list_images()


@router.get("/{image_id}")
def image_info(image_id: str) -> dict:
    try:
        return describe(image_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RasterError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{image_id}/preview")
def image_preview(image_id: str) -> Response:
    try:
        image = cached_preview(image_file(image_id))
        return Response(image, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=600"})
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RasterError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{image_id}/pyramid")
def image_pyramid(image_id:str):
    from .pyramid import pyramid_info
    try:
        return pyramid_info(image_file(image_id))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404,detail=str(error)) from error
    except (RasterError,ValueError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.get("/{image_id}/tiles/{level}/{x}/{y}.png")
def image_tile(image_id:str,level:int,x:int,y:int):
    from .pyramid import cached_tile
    try:
        png=cached_tile(image_file(image_id),level,x,y)
        return Response(png,media_type="image/png",headers={"Cache-Control":"private, max-age=60"})
    except FileNotFoundError as error:
        raise HTTPException(status_code=404,detail=str(error)) from error
    except (RasterError,ValueError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/upload", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token"),
) -> dict:
    try:
        require_admin(token)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    if not file.filename or not file.filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(status_code=422, detail="Upload a georeferenced .tif/.tiff file.")
    root = imagery_dir()
    root.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".import-", suffix=".tif", dir=root)
    total = 0
    try:
        with os.fdopen(handle, "wb") as target:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="GeoTIFF exceeds 64 MB limit.")
                target.write(chunk)
        if total == 0:
            raise HTTPException(status_code=422, detail="The GeoTIFF is empty.")
        return await run_in_threadpool(store_upload, __import__("pathlib").Path(temporary), file.filename)
    except RasterError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
        if os.path.exists(temporary):
            os.unlink(temporary)



class CatalogSearchRequest(BaseModel):
    bbox: tuple[float, float, float, float]
    collection: str = "sentinel-2-l2a"
    limit: int = Field(default=8, ge=1, le=12)
    start_date: date | None = None
    end_date: date | None = None


@router.post("/catalog/search")
async def public_imagery_search(body: CatalogSearchRequest) -> dict:
    try:
        return await search_stac(
            body.bbox, body.collection, body.limit, body.start_date, body.end_date,
        )
    except CatalogSearchError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=503, detail="Public imagery catalog is unavailable.") from error
