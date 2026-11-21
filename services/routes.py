"""Authenticated OGC source management with secure bounded raster/vector proxies."""
from typing import Literal
from fastapi import APIRouter,Header,HTTPException,Query
from fastapi.responses import Response
from pydantic import BaseModel,Field
from intelligence.catalog import require_admin
from storage.database import StorageError
from .ogc import (OGCError,add_source,list_sources,delete_source,
                  capabilities,fetch_features,fetch_tile)

router=APIRouter(prefix="/projects",tags=["OGC"])

def fail(error):
    return HTTPException(status_code=404 if "not found" in str(error).lower()
                         else 422,detail=str(error))
def admin(token):
    try:require_admin(token)
    except PermissionError as error:
        raise HTTPException(status_code=403,detail=str(error)) from error

class OGCDefinition(BaseModel):
    service:Literal["wms","wmts","wfs","ogc_features"]
    title:str=Field(min_length=1,max_length=100)
    base_url:str=Field(min_length=9,max_length=500)
    layer_name:str=Field(min_length=1,max_length=100)
    attribution:str=Field(default="",max_length=240)
    tile_matrix_set:str="GoogleMapsCompatible"

@router.get("/{project_id}/ogc")
def sources(project_id:str):
    try:return {"sources":list_sources(project_id)}
    except StorageError as error:raise fail(error) from error

@router.post("/{project_id}/ogc",status_code=201)
def register_source(project_id:str,body:OGCDefinition,
          token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    admin(token)
    try:return add_source(project_id,**body.model_dump())
    except (OGCError,StorageError) as error:raise fail(error) from error

@router.delete("/{project_id}/ogc/{source_id}",status_code=204)
def remove_source(project_id:str,source_id:str,
          token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    admin(token)
    try:delete_source(project_id,source_id)
    except (OGCError,StorageError) as error:raise fail(error) from error

@router.get("/{project_id}/ogc/{source_id}/capabilities")
def inspect_service(project_id:str,source_id:str):
    try:return capabilities(project_id,source_id)
    except (OGCError,StorageError) as error:raise fail(error) from error

@router.get("/{project_id}/ogc/{source_id}/features")
def vector_features(project_id:str,source_id:str,west:float,south:float,east:float,north:float,
                    limit:int=Query(default=100,ge=1,le=100)):
    try:return fetch_features(project_id,source_id,(west,south,east,north),limit)
    except (OGCError,StorageError) as error:raise fail(error) from error

@router.get("/{project_id}/ogc/{source_id}/tiles/{z}/{x}/{y}")
def raster_tile(project_id:str,source_id:str,z:int,x:int,y:int):
    try:data,mime=fetch_tile(project_id,source_id,z,x,y)
    except (OGCError,StorageError) as error:raise fail(error) from error
    return Response(data,media_type=mime,headers={"Cache-Control":"private, max-age=300"})
