"""Select by location and inspect data topology in local projects."""
from typing import Literal,Any
from fastapi import APIRouter,HTTPException,Query
from pydantic import BaseModel,Field
from storage.database import StorageError
from storage.paging import page_features
from geometry.measure import GeometryError
from .selection import select_features
from .topology_qa import review_topology

router=APIRouter(prefix="/projects",tags=["spatial-workflows"])

class SpatialSelect(BaseModel):
    geometry:dict[str,Any]
    relation:Literal["intersects","within","contains","touches","crosses"]="intersects"
    layer_ids:list[str]|None=Field(default=None,max_length=100)
    visible_only:bool=True
    limit:int=Field(default=200,ge=1,le=500)
    offset:int=Field(default=0,ge=0,le=100000)

class QualityReport(BaseModel):
    layer_ids:list[str]|None=Field(default=None,max_length=100)
    study_area:dict[str,Any]|None=None
    minimum_area_m2:float=Field(default=0.01,ge=0,le=1_000_000_000)
    check_dangles:bool=True
    max_issues:int=Field(default=250,ge=1,le=1000)

@router.post("/{project_id}/spatial/select")
def select(project_id:str,body:SpatialSelect):
    try:return select_features(project_id,body.geometry,body.relation,
                body.layer_ids,body.limit,body.offset,body.visible_only)
    except (StorageError,GeometryError) as error:
        raise HTTPException(status_code=404 if "not found" in str(error).lower()
                           else 422,detail=str(error)) from error

@router.post("/{project_id}/quality/topology")
def quality(project_id:str,body:QualityReport):
    try:return review_topology(project_id,body.layer_ids,body.study_area,
                               body.minimum_area_m2,body.check_dangles,body.max_issues)
    except (StorageError,GeometryError) as error:
        raise HTTPException(status_code=404 if "not found" in str(error).lower()
                           else 422,detail=str(error)) from error

@router.get("/{project_id}/features/viewport")
def viewport(project_id:str,west:float,south:float,east:float,north:float,
             limit:int=Query(250,ge=1,le=1000),offset:int=Query(0,ge=0,le=1_000_000),
             visible_only:bool=True):
    try:return page_features(project_id,(west,south,east,north),limit,offset,
                             visible_only=visible_only)
    except StorageError as error:
        raise HTTPException(status_code=404 if "not found" in str(error).lower()
                           else 422,detail=str(error)) from error
