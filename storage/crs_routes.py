"""Per-project EPSG coordinate references and map grid endpoints."""
from fastapi import APIRouter,HTTPException,Query
from pydantic import BaseModel,Field
from storage.database import StorageError
from .crs import get_crs,update_crs,transform_positions,projected_grid
router=APIRouter(prefix="/projects",tags=["coordinate-systems"])

class ProjectCrsUpdate(BaseModel):
    epsg:str=Field(min_length=6,max_length=24)
    grid_visible:bool=False
    expected_revision:int|None=Field(default=None,ge=0)

class CoordinatesTransform(BaseModel):
    points:list[tuple[float,float]]=Field(min_length=1,max_length=2000)
    source:str="EPSG:4326"
    target:str="EPSG:3857"

def fail(error):
    message=str(error)
    return HTTPException(status_code=409 if "conflict" in message.lower()
        else 404 if "not found" in message.lower() else 422,detail=message)

@router.get("/{project_id}/crs")
def project_coordinates(project_id:str):
    try:return get_crs(project_id)
    except StorageError as error:raise fail(error) from error

@router.put("/{project_id}/crs")
def change_project_coordinates(project_id:str,body:ProjectCrsUpdate):
    try:return update_crs(project_id,body.epsg,body.grid_visible,body.expected_revision)
    except StorageError as error:raise fail(error) from error

@router.post("/{project_id}/crs/transform")
def transform_coordinates(project_id:str,body:CoordinatesTransform):
    try:
        get_crs(project_id)
        return transform_positions(body.points,body.source,body.target)
    except StorageError as error:raise fail(error) from error

@router.get("/{project_id}/crs/grid")
def get_project_grid(project_id:str,west:float,south:float,east:float,north:float,
                     divisions:int=Query(default=5,ge=2,le=10)):
    try:return projected_grid(project_id,(west,south,east,north),divisions)
    except StorageError as error:raise fail(error) from error
