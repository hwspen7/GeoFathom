"""DEM area statistics and elevation cross sections."""

from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from starlette.concurrency import run_in_threadpool

from imagery.raster import RasterError
from imagery.store import image_file
from geometry.measure import GeometryError
from .engine import analyze_area,elevation_profile

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
async def area(body:TerrainInput)->dict:
    try:
        return await run_in_threadpool(analyze_area,raster(body.image_id),
                                       body.geometry,body.vertical_unit)
    except (GeometryError,RasterError,ValueError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.post("/profile")
async def profile(body:TerrainInput)->dict:
    try:
        return await run_in_threadpool(elevation_profile,raster(body.image_id),
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

@router.post("/advanced")
async def advanced(body:AdvancedTerrainInput):
    from .advanced import run_terrain
    try:
        return await run_in_threadpool(run_terrain,raster(body.image_id),body.geometry,
            body.operation,body.interval,body.reference,body.point,body.observer_height,body.target_height)
    except (GeometryError,RasterError,ValueError,OverflowError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
