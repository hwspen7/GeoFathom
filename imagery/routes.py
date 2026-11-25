"""Local GeoTIFF ingest and georeferenced preview endpoints."""

import os
from datetime import date
import tempfile

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, Request
from core.config import get_settings
from core.security import _loopback, local_raster_import_enabled
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


def require_raster_import(request: Request, token: str | None):
    # A single-user local desktop may import its own imagery without a
    # model-management token. Deployed/explicitly protected servers retain
    # the administrator check. A non-simple header prevents cross-site forms.
    origin = request.headers.get("origin")
    local_import = (
        local_raster_import_enabled()
        and request.client is not None and _loopback(request.client.host)
        and request.headers.get("X-GeoFathom-Local-Import") == "1"
        and (origin is None or origin in get_settings().cors_origins)
    )
    if not local_import:
        try:
            require_admin(token)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

@router.post("/upload", status_code=201)
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token"),
) -> dict:
    require_raster_import(request, token)
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



class DEMFetchRequest(BaseModel):
    bbox: tuple[float,float,float,float]
    resolution_m: int = 30


@router.post("/dem/fetch",status_code=201)
async def fetch_dem(body:DEMFetchRequest,request:Request,
    token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    """Fetch validated 3DEP or Copernicus terrain; abandon stale client requests safely."""
    require_raster_import(request,token)
    from .public_dem import fetch_dem_subset
    try:
        from terrain.routes import run_cancelable
        return await run_cancelable(request,fetch_dem_subset,body.bbox,body.resolution_m)
    except RasterError as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
