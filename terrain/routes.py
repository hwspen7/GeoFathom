"""DEM area statistics and elevation cross sections."""

import asyncio
from threading import Event
from fastapi import APIRouter,HTTPException,Request
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
        return await run_cancelable(request,elevation_profile,raster(body.image_id),
                                       body.geometry,body.samples)
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

@router.post("/advanced")
async def advanced(request:Request,body:AdvancedTerrainInput):
    from .advanced import run_terrain
    try:
        return await run_cancelable(request,run_terrain,raster(body.image_id),body.geometry,
            body.operation,body.interval,body.reference,body.point,body.observer_height,body.target_height,
            body.end_point,body.max_slope,body.min_elevation,body.max_elevation,body.max_tri,body.stream_cells,body.azimuth,body.altitude,
            body.section_spacing,body.section_width,raster(body.texture_image_id) if body.texture_image_id and body.operation=='mesh' else None,
            body.fill_sinks,body.consider_curvature,body.refraction_coeff,
            raster(body.comparison_image_id) if body.operation=="dem_difference" and body.comparison_image_id else None)
    except (GeometryError,RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
