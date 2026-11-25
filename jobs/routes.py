"""Persistent geospatial task queue API with cooperative cancellation."""
from typing import Any,Literal
import json
from fastapi import APIRouter,Header,HTTPException,Query,Request
from fastapi.responses import Response,FileResponse
from pydantic import BaseModel,Field
from intelligence.catalog import require_admin
from storage.database import StorageError
from .queue import queue_job,list_jobs,get_job,cancel_job

router=APIRouter(prefix="/projects",tags=["background-jobs"])

class SubmitJob(BaseModel):
    kind:Literal["topology_qa","spatial_select","export_geojson",
                 "postgis_sync","rebuild_index","spectral_index",
                 "spectral_change","semantic_segmentation","stac_ndvi","remote_windowed","remote_cube"]
    payload:dict[str,Any]=Field(default_factory=dict)

def fail(error):
    return HTTPException(status_code=404 if "not found" in str(error).lower()
        else 422,detail=str(error))

@router.post("/{project_id}/jobs",status_code=202)
def submit(project_id:str,body:SubmitJob,request:Request,
           token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    if getattr(request.state,"principal",None) and body.kind not in {"topology_qa","spatial_select","export_geojson"}:
        raise HTTPException(status_code=403,detail="Operator-only job.")
    if body.kind in {"remote_windowed","remote_cube"}:
        from imagery.routes import require_raster_import
        require_raster_import(request,token)
    if body.kind in {"postgis_sync","rebuild_index","spectral_index",
                     "spectral_change","semantic_segmentation","stac_ndvi"}:
        try:require_admin(token)
        except PermissionError as error:
            raise HTTPException(status_code=403,detail=str(error)) from error
    try:return queue_job(project_id,body.kind,body.payload)
    except (StorageError,ValueError) as error:raise fail(error) from error

@router.get("/{project_id}/jobs")
def list_project_jobs(project_id:str,limit:int=Query(default=30,ge=1,le=100)):
    try:return {"jobs":list_jobs(project_id,limit)}
    except StorageError as error:raise fail(error) from error

@router.get("/{project_id}/jobs/{job_id}")
def job_status(project_id:str,job_id:str,include_result:bool=True):
    try:return get_job(project_id,job_id,include_result=include_result)
    except StorageError as error:raise fail(error) from error

@router.post("/{project_id}/jobs/{job_id}/cancel")
def cancel(project_id:str,job_id:str):
    try:return cancel_job(project_id,job_id)
    except StorageError as error:raise fail(error) from error

@router.get("/{project_id}/jobs/{job_id}/download")
def download_result(project_id:str,job_id:str):
    try:
        job=get_job(project_id,job_id)
        if job["kind"] in {"remote_windowed","remote_cube"} and job["status"]=="completed":
            from imagery.remote_managed import result_path
            path=result_path(job_id)
            if not path.is_file():raise StorageError("Remote raster result not found.")
            return FileResponse(path,media_type="image/tiff",filename="remote-sensing.tif",headers={"Cache-Control":"no-store"})
        if job["kind"]!="export_geojson" or job["status"]!="completed":
            raise StorageError("Completed GeoJSON export job required.")
        return Response(json.dumps(job["result"],ensure_ascii=False).encode("utf-8"),
            media_type="application/geo+json",headers={
                "Content-Disposition":'attachment; filename="geofathom-export.geojson"',
                "Cache-Control":"no-store",
            })
    except StorageError as error:raise fail(error) from error


@router.post("/{project_id}/jobs/{job_id}/imagery",status_code=201)
def register_result(project_id:str,job_id:str,request:Request,
                    token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    from imagery.routes import require_raster_import
    from imagery.remote_managed import result_path
    from imagery.remote_windowed import digest
    from imagery.cli import import_local_image
    require_raster_import(request,token)
    try:
        job=get_job(project_id,job_id)
        if job['kind'] not in {'remote_cube','remote_windowed'} or job['status']!='completed':
            raise StorageError('A completed scientific raster job is required.')
        path=result_path(job_id)
        if not path.is_file() or digest(path)!=job['result']['sha256']:
            raise StorageError('Scientific raster result is missing or changed.')
        return import_local_image(path,job['kind']+'-'+job_id+'.tif')
    except (StorageError,ValueError,OSError) as error:raise fail(error) from error
