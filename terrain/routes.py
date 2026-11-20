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
