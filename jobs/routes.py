"""Persistent geospatial task queue API with cooperative cancellation."""
from typing import Any,Literal
import json
from fastapi import APIRouter,Header,HTTPException,Query
from fastapi.responses import Response
from pydantic import BaseModel,Field
from intelligence.catalog import require_admin
from storage.database import StorageError
from .queue import queue_job,list_jobs,get_job,cancel_job

router=APIRouter(prefix="/projects",tags=["background-jobs"])

class SubmitJob(BaseModel):
    kind:Literal["topology_qa","spatial_select","export_geojson","postgis_sync","rebuild_index"]
    payload:dict[str,Any]=Field(default_factory=dict)

def fail(error):
    return HTTPException(status_code=404 if "not found" in str(error).lower()
        else 422,detail=str(error))

@router.post("/{project_id}/jobs",status_code=202)
def submit(project_id:str,body:SubmitJob,
           token:str|None=Header(default=None,alias="X-GeoFathom-Admin-Token")):
    if body.kind in {"postgis_sync","rebuild_index"}:
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
def job_status(project_id:str,job_id:str):
    try:return get_job(project_id,job_id)
    except StorageError as error:raise fail(error) from error

@router.post("/{project_id}/jobs/{job_id}/cancel")
def cancel(project_id:str,job_id:str):
    try:return cancel_job(project_id,job_id)
    except StorageError as error:raise fail(error) from error

@router.get("/{project_id}/jobs/{job_id}/download")
def download_result(project_id:str,job_id:str):
    try:
        job=get_job(project_id,job_id)
        if job["kind"]!="export_geojson" or job["status"]!="completed":
            raise StorageError("Completed GeoJSON export job required.")
        return Response(json.dumps(job["result"],ensure_ascii=False).encode("utf-8"),
            media_type="application/geo+json",headers={
                "Content-Disposition":'attachment; filename="geofathom-export.geojson"',
                "Cache-Control":"no-store",
            })
    except StorageError as error:raise fail(error) from error
