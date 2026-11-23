"""DEM area statistics and elevation cross sections."""

import asyncio
from threading import Event
from fastapi import APIRouter,HTTPException,Request,Header
from pydantic import BaseModel,Field
from starlette.concurrency import run_in_threadpool

from imagery.raster import RasterError
from imagery.store import image_file
from geometry.measure import GeometryError
from .engine import analyze_area,elevation_profile
from .cancellation import TerrainCancelled


async def run_cancelable(request, fn, *args):
    # Do not abandon a worker on browser disconnect: request cancellation
    # is observed at the algorithm checkpoints, and the worker is drained.
    cancel=Event()
    task=asyncio.create_task(run_in_threadpool(fn,*args,cancel=cancel))
    try:
        while not task.done():
            await asyncio.wait({task},timeout=.1)
            if not task.done() and await request.is_disconnected():
                cancel.set()
        return await task
    except TerrainCancelled as error:
        raise HTTPException(status_code=499,detail=str(error)) from error
    finally:
        cancel.set()
        if not task.done():
            try:await asyncio.shield(task)
            except (TerrainCancelled,asyncio.CancelledError):pass


router=APIRouter(prefix="/terrain",tags=["terrain"])


class TerrainInput(BaseModel):
    image_id:str
    geometry:dict
    vertical_unit:str="meter"
    samples:int=Field(default=80,ge=4,le=250)


def raster(identifier):
    try:return image_file(identifier)
    except FileNotFoundError as error:raise HTTPException(status_code=404,detail=str(error)) from error
    except RasterError as error:raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/analyze")
async def area(request:Request,body:TerrainInput)->dict:
    try:
        return await run_cancelable(request,analyze_area,raster(body.image_id),
                                       body.geometry,body.vertical_unit)
    except (GeometryError,RasterError,ValueError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/profile")
async def profile(request:Request,body:TerrainInput)->dict:
    try:
        # Profile elevations and output field names are always in meters.
        # Honor the API unit contract rather than silently accepting feet.
        if body.vertical_unit!="meter":
            raise RasterError("Terrain model currently supports vertical elevations in meters only.")
        return await run_cancelable(request,elevation_profile,raster(body.image_id),
                                       body.geometry,body.samples)
    except (GeometryError,RasterError,ValueError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class DEMPrepareInput(BaseModel):
    image_ids:list[str]=Field(min_length=1,max_length=4)
    mode:str
    geometry:dict|None=None
    resolution_m:float|None=Field(default=None,ge=1,le=1000)
    sampling:str="bilinear"


@router.post("/dem/prepare",status_code=201)
async def prepare_dem_asset(request:Request,body:DEMPrepareInput,
                            token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    """Prepare a locally stored elevation product with the import permission."""
    from imagery.routes import require_raster_import
    from .dem_processing import prepare_dem
    require_raster_import(request,token)
    try:
        paths=[raster(identifier) for identifier in body.image_ids]
        return await run_cancelable(request,prepare_dem,paths,body.mode,
                                    body.geometry,body.resolution_m,body.sampling)
    except (GeometryError,RasterError,ValueError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class AdvancedTerrainInput(BaseModel):
    image_id:str
    geometry:dict
    operation:str
    interval:float=Field(default=10,gt=0)
    reference:float=0
    point:tuple[float,float]|None=None
    observer_height:float=Field(default=1.7,ge=0,le=1000)
    target_height:float=Field(default=0,ge=0,le=1000)
    end_point:tuple[float,float]|None=None
    max_slope:float=Field(default=30,ge=0,le=90)
    min_elevation:float=Field(default=-12000,ge=-12000,le=12000)
    max_elevation:float=Field(default=12000,ge=-12000,le=12000)
    max_tri:float=Field(default=100,ge=0,le=100000)
    stream_cells:int=Field(default=100,ge=1,le=1000000)
    azimuth:float=Field(default=315,ge=0,le=360)
    altitude:float=Field(default=45,ge=0,le=90)
    section_spacing:float=Field(default=50,ge=1,le=10000)
    section_width:float=Field(default=20,ge=1,le=2000)
    texture_image_id:str|None=None
    fill_sinks:bool=False
    consider_curvature:bool=False
    refraction_coeff:float=Field(default=0.13,ge=0,le=0.5)
    comparison_image_id:str|None=None
    observer_points:list[tuple[float,float]]|None=Field(default=None,min_length=2,max_length=4)

@router.post("/advanced")
async def advanced(request:Request,body:AdvancedTerrainInput):
    from .advanced import run_terrain
    try:
        return await run_cancelable(request,run_terrain,raster(body.image_id),body.geometry,
            body.operation,body.interval,body.reference,body.point,body.observer_height,body.target_height,
            body.end_point,body.max_slope,body.min_elevation,body.max_elevation,body.max_tri,body.stream_cells,body.azimuth,body.altitude,
            body.section_spacing,body.section_width,raster(body.texture_image_id) if body.texture_image_id and body.operation=='mesh' else None,
            body.fill_sinks,body.consider_curvature,body.refraction_coeff,
            raster(body.comparison_image_id) if body.operation=="dem_difference" and body.comparison_image_id else None,
            body.observer_points)
    except (GeometryError,RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class ResearchCriterionInput(BaseModel):
    image_id:str
    name:str=Field(min_length=1,max_length=80)
    direction:str
    low:float
    high:float
    target:float|None=None
    weight:float=Field(default=1,gt=0)
    sigma:float=Field(default=0,ge=0)
    weight_sigma:float=Field(default=0,ge=0,le=1)
    allowed_min:float|None=None
    allowed_max:float|None=None
    sampling:str="bilinear"
    vertical_elevation:bool=False


class ResearchInput(BaseModel):
    image_id:str
    geometry:dict
    criteria:list[ResearchCriterionInput]=Field(min_length=2,max_length=8)
    threshold:float=Field(default=.65,ge=0,le=1)
    sensitivity_fraction:float=Field(default=.2,gt=0,le=.5)
    trials:int=Field(default=64,ge=0,le=256)
    seed:int=Field(default=42,ge=0,lt=4294967296)
    pairwise:list[list[float]]|None=None


@router.post("/research")
async def research(request:Request,body:ResearchInput):
    """Bounded, source-ID-only multicriteria GIS study with a portable evidence bundle."""
    from .research import analyze_research
    try:
        # Client-provided filesystem paths are never accepted. All inputs
        # resolve through managed imagery IDs with the normal API access policy.
        criteria=[{**entry.model_dump(), "path":raster(entry.image_id)}
                  for entry in body.criteria]
        options={"threshold":body.threshold,"sensitivity_fraction":body.sensitivity_fraction,
                 "trials":body.trials,"seed":body.seed,"pairwise":body.pairwise}
        return await run_cancelable(request,analyze_research,raster(body.image_id),
                                    body.geometry,criteria,options)
    except (GeometryError,RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class ElevationCheckpoint(BaseModel):
    longitude:float
    latitude:float
    elevation_m:float


class CheckpointValidationInput(BaseModel):
    image_id:str
    points:list[ElevationCheckpoint]=Field(min_length=5,max_length=10000)
    vertical_datum:str|None=None


@router.post("/research/checkpoints")
async def research_checkpoints(request:Request,body:CheckpointValidationInput):
    """Observed-minus-reference DEM error metrics from independently supplied GCPs."""
    from .research import checkpoint_accuracy
    try:
        return await run_cancelable(request,checkpoint_accuracy,raster(body.image_id),
                                    [point.model_dump() for point in body.points],
                                    body.vertical_datum)
    except (RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


class ResearchArchiveInput(BaseModel):
    archive_base64:str=Field(max_length=100_000_000)


@router.post("/research/verify")
async def research_verify(request:Request,body:ResearchArchiveInput):
    """Verify SHA-256 and archive structure for a portable research evidence set."""
    import base64
    import binascii
    from .research import verify_research_bundle
    try:
        raw=base64.b64decode(body.archive_base64,validate=True)
        return await run_cancelable(request,verify_research_bundle,raw)
    except (RasterError,ValueError,binascii.Error) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
