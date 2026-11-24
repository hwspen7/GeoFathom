"""DEM area statistics and elevation cross sections."""

import asyncio
from threading import Event
from typing import Literal
from fastapi import APIRouter,HTTPException,Request,Header
from pydantic import BaseModel,Field,model_validator
from starlette.concurrency import run_in_threadpool

from imagery.raster import RasterError
from imagery.store import image_file
from geometry.measure import GeometryError
from .engine import analyze_area,elevation_profile
from .cancellation import TerrainCancelled
from .catalog import terrain_catalog
from .compute_resources import task_resources, ResourceBusy
from dataclasses import asdict


async def run_cancelable(request, fn, *args, budgeted=False):
    # Do not abandon a worker on browser disconnect: request cancellation
    # is observed at the algorithm checkpoints, and the worker is drained.
    cancel=Event()
    def execute():
        if not budgeted:
            return fn(*args,cancel=cancel)
        with task_resources(cancel) as limits:
            result=fn(*args,cancel=cancel)
            if isinstance(result,dict):
                result["compute_resources"]=asdict(limits)
            return result
    task=asyncio.create_task(run_in_threadpool(execute))
    try:
        while not task.done():
            await asyncio.wait({task},timeout=.1)
            if not task.done() and await request.is_disconnected():
                cancel.set()
        return await task
    except ResourceBusy as error:
        raise HTTPException(status_code=409,detail=str(error)) from error
    except TerrainCancelled as error:
        raise HTTPException(status_code=499,detail=str(error)) from error
    finally:
        cancel.set()
        if not task.done():
            try:await asyncio.shield(task)
            except (TerrainCancelled,asyncio.CancelledError):pass


router=APIRouter(prefix="/terrain",tags=["terrain"])


@router.get("/catalog")
def catalog():
    return terrain_catalog()


class TerrainInput(BaseModel):
    image_id:str
    geometry:dict
    vertical_unit:str="meter"
    gradient_method:Literal["horn","zevenbergen_thorne"]="horn"
    samples:int=Field(default=80,ge=4,le=250)


def raster(identifier):
    try:return image_file(identifier)
    except FileNotFoundError as error:raise HTTPException(status_code=404,detail=str(error)) from error
    except RasterError as error:raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/analyze")
async def area(request:Request,body:TerrainInput)->dict:
    try:
        return await run_cancelable(request,analyze_area,raster(body.image_id),
                                       body.geometry,body.vertical_unit,body.gradient_method,budgeted=True)
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
    observer_points:list[tuple[float,float]]|None=Field(default=None,min_length=2,max_length=12)
    gradient_method:Literal['horn','zevenbergen_thorne']='horn'
    slope_classes:Literal['standard','detailed','broad']='standard'
    mfd_exponent:float=Field(default=1.1,ge=0.5,le=8.0)
    neighborhood_radius:int=Field(default=1,ge=1,le=4)
    max_distance_m:float=Field(default=0,ge=0,le=100000)
    view_azimuth:float=Field(default=0,ge=0,le=360)
    view_width:float=Field(default=360,gt=0,le=360)
    route_model:Literal['surface','distance','gentle']='surface'
    mesh_samples:int=Field(default=256,ge=64,le=512)
    stream_order_scheme:Literal['strahler','shreve']='strahler'
    hillshade_mode:Literal['single','four_direction']='single'
    flow_routing_method:Literal['d8','dinf']='d8'
    depression_method:Literal['fill','breach']='fill'
    curvature_method:Literal['finite_difference','quadratic']='finite_difference'
    curvature_radius:int=Field(default=2,ge=1,le=4)
    design_east_grade:float=Field(default=0,ge=-1,le=1)
    design_north_grade:float=Field(default=0,ge=-1,le=1)
    design_max_grade:float=Field(default=0.3,gt=0,le=1)
    elevation_sigma_m:float=Field(default=0,ge=0,le=10000)
    optimize_observers:int=Field(default=0,ge=0,le=4)
    dsm_image_id:str|None=None
    mesh_lod:bool=False
    suitability_model:Literal['binary','weighted']='binary'
    suitability_weights:tuple[float,float,float]=(0.5,0.25,0.25)
    external_inflow_image_id:str|None=None
    design_curvature_east:float=Field(default=0,ge=-1,le=1)
    design_curvature_cross:float=Field(default=0,ge=-1,le=1)
    design_curvature_north:float=Field(default=0,ge=-1,le=1)

    @model_validator(mode="after")
    def check_p1_candidate_bounds(self):
        if self.observer_points and len(self.observer_points)>4 and not self.optimize_observers:
            raise ValueError("More than four candidate observers requires enabled site optimization.")
        if self.observer_points and self.optimize_observers>len(self.observer_points):
            raise ValueError("Cannot optimize more observation sites than candidates.")
        return self

class MeshTileInput(BaseModel):
    image_id:str
    geometry:dict
    level:Literal[1,2,4,8,16,32,64]
    tile_row:int=Field(ge=0,le=127)
    tile_col:int=Field(ge=0,le=127)
    tile_cells:Literal[32]=32


@router.post("/mesh/tile")
async def mesh_tile(request:Request,body:MeshTileInput):
    """Fetch one exact source-window tile; do not materialize the entire DEM."""
    from .mesh_tiles import stream_mesh_tile
    try:
        return await run_cancelable(request,stream_mesh_tile,raster(body.image_id),
            body.geometry,body.level,body.tile_row,body.tile_col,body.tile_cells)
    except (GeometryError,RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


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
            body.observer_points,body.gradient_method,body.slope_classes,
            body.mfd_exponent,body.neighborhood_radius,
            body.max_distance_m,body.view_azimuth,body.view_width,
            body.route_model,body.mesh_samples,body.stream_order_scheme,body.hillshade_mode,
            body.flow_routing_method,body.depression_method,body.curvature_method,body.curvature_radius,
            body.design_east_grade,body.design_north_grade,body.design_max_grade,body.elevation_sigma_m,
            body.optimize_observers,
            raster(body.dsm_image_id) if body.dsm_image_id and body.operation in {"visibility","viewshed_multi"} else None,
            body.mesh_lod,body.suitability_model,body.suitability_weights,
            raster(body.external_inflow_image_id) if body.external_inflow_image_id else None,
            body.design_curvature_east,body.design_curvature_cross,body.design_curvature_north,budgeted=True)
    except (GeometryError,RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
