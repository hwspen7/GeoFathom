"""Network research API; all computations use explicit input graphs."""
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from typing import Annotated
from .network_science import METHODS,execute,NetworkError
from rasterio.errors import RasterioError
from pyproj.exceptions import ProjError

router=APIRouter(prefix="/analysis/network-science",tags=["network science"])
Positive=Annotated[float,Field(gt=0,le=1e12)]
class ExposureRaster(BaseModel):
    model_config=ConfigDict(extra="forbid")
    data:str=Field(max_length=16_000_000)
    band:int=Field(default=1,ge=1,le=1024)

class NetworkInput(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    operation:str=Field(max_length=80)
    network:dict
    cost_field:str=Field(default="length_m",min_length=1,max_length=80)
    cost_unit:str=Field(default="cost",min_length=1,max_length=80)
    origins:list[str]=Field(default_factory=list,max_length=256)
    destinations:list[str]=Field(default_factory=list,max_length=256)
    demand:dict[str,Positive]=Field(default_factory=dict,max_length=256)
    supply:dict[str,Positive]=Field(default_factory=dict,max_length=256)
    threshold:Positive=1000
    beta:Annotated[float,Field(gt=0,le=1000)]=.001
    closed_edges:list[str]=Field(default_factory=list,max_length=10000)
    multipliers:dict[str,Positive]=Field(default_factory=dict,max_length=10000)
    test_edges:list[str]=Field(default_factory=list,max_length=256)
    failure_probability:dict[str,Annotated[float,Field(ge=0,le=1)]]=Field(default_factory=dict,max_length=10000)
    trials:int=Field(default=200,ge=20,le=2000)
    seed:int=Field(default=42,ge=0,le=2147483647)
    secondary_cost_field:str=Field(default='length_m',min_length=1,max_length=80)
    secondary_cost_unit:str=Field(default='m',min_length=1,max_length=80)
    spatial_range_m:Annotated[float,Field(ge=1,le=1e7)]=1000
    exposure_reference:Annotated[float,Field(ge=-1e12,le=1e12)]=0
    exposure_scale:Positive=1
    exposure_alpha:Annotated[float,Field(ge=0,le=100)]=1
    raster:ExposureRaster|None=None
    spacing_m:Annotated[float,Field(ge=1,le=10000)]=30
    minimum_coverage:Annotated[float,Field(gt=0,le=1)]=1
    hazard_threshold:Annotated[float,Field(ge=-1e12,le=1e12)]=.5

@router.get("/catalog")
def catalog():
    return {"operations":[{"id":k,"title":v[0],"assumption":v[1]} for k,v in METHODS.items()],"input_schema":NetworkInput.model_json_schema()}

@router.post("/run")
def run(body:NetworkInput):
    try:return execute(body)
    except (NetworkError,ValueError,TypeError,OverflowError,RasterioError,ProjError) as e:raise HTTPException(422,detail=str(e)) from e

class OSMInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    snapshot:dict
    speed_kmh_by_class:dict[str,Annotated[float,Field(ge=.1,le=200)]]=Field(min_length=1,max_length=40)

@router.post('/build-osm')
def build(body:OSMInput):
    from .network_import import build_osm
    try:return build_osm(body.snapshot,body.speed_kmh_by_class)
    except (ValueError,TypeError,OverflowError) as e:raise HTTPException(422,detail=str(e)) from e
