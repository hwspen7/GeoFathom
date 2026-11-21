"""Optional PostGIS synchronization and indexed regional query APIs."""
from fastapi import APIRouter,Header,HTTPException,Query
from pydantic import BaseModel,Field
from intelligence.catalog import require_admin
from storage.database import StorageError
from .postgis import PostGISError,status,sync_project,spatial_page,purge_project

router=APIRouter(tags=["postgis"])

def _error(error):
    return HTTPException(status_code=404 if "not found" in str(error).lower()
        else 503 if isinstance(error,PostGISError) else 422,detail=str(error))

@router.get("/postgis/status")
def postgis_status():return status()

class SyncLimit(BaseModel):
    max_features:int=Field(default=100000,ge=1,le=100000)

@router.post("/projects/{project_id}/postgis/sync")
def sync_postgis(project_id:str,body:SyncLimit,
                token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    try:
        require_admin(token)
        return sync_project(project_id,body.max_features)
    except PermissionError as error:raise HTTPException(status_code=403,detail=str(error)) from error
    except (PostGISError,StorageError) as error:raise _error(error) from error

@router.get("/projects/{project_id}/postgis/features")
def indexed_postgis_features(project_id:str,west:float,south:float,east:float,north:float,
                             limit:int=Query(250,ge=1,le=1000),
                             offset:int=Query(0,ge=0,le=1000000)):
    try:return spatial_page(project_id,(west,south,east,north),limit,offset)
    except (PostGISError,StorageError) as error:raise _error(error) from error

@router.delete("/projects/{project_id}/postgis")
def drop_postgis_mirror(project_id:str,
                token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    try:require_admin(token);return purge_project(project_id)
    except PermissionError as error:raise HTTPException(status_code=403,detail=str(error)) from error
    except (PostGISError,StorageError) as error:raise _error(error) from error
