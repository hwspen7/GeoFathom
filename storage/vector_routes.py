"""Validated synchronous interchange and staged, cancellable batch workflows."""
import json
import shutil
from pathlib import Path
from uuid import uuid4
from typing import Literal,Any

from fastapi import APIRouter,File,UploadFile,HTTPException,Body,Request,Header
from fastapi.responses import Response,FileResponse
from pydantic import BaseModel,Field,ConfigDict
from starlette.concurrency import run_in_threadpool
from .vectorio import MAX_BYTES,VectorIOError,read_vector,dumps
from .database import StorageError,_connect,_required_project
from .exchange import (stage_path,inspect_staged,commit_import,perform_export,preflight,get_artifact,discard_stage)
from jobs.queue import queue_job,get_job

router=APIRouter(prefix='/projects',tags=['vector-io'])

class ImportOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    layers:list[str]|None=Field(default=None,max_length=100)
    source_crs:str|None=None
    encoding:Literal['utf-8','utf-8-sig','utf-16','cp1252','gb18030']='utf-8'
    error_policy:Literal['strict','skip']='strict'
    field_map:dict[str,str]=Field(default_factory=dict,max_length=1000)
    field_types:dict[str,Literal['integer','number','boolean','string','json']]=Field(default_factory=dict,max_length=1000)
    longitude_field:str='longitude'
    latitude_field:str='latitude'
    geometry_field:str|None=None
    delimiter:Literal[',',';','\t','|']=','

class FileSelection(BaseModel):
    id:str
    options:ImportOptions=Field(default_factory=ImportOptions)

class BatchRequest(BaseModel):
    upload_id:str
    files:list[FileSelection]=Field(default_factory=list,max_length=20)
    layer_id:str|None=None
    separate_layers:bool=True

class ExportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    format:Literal['geojson','gpkg','shapefile','kml','gpx','csv','report']
    target_crs:str='EPSG:4326'
    include_measurements:bool=False
    layer_ids:list[str]|None=Field(default=None,max_length=100)
    feature_ids:list[str]|None=Field(default=None,max_length=100000)
    viewport:tuple[float,float,float,float]|None=None
    fields:list[str]|None=Field(default=None,max_length=1000)
    precision:int|None=Field(default=None,ge=0,le=15)
    collection:dict[str,Any]|None=None

def fail(error):
    return HTTPException(status_code=404 if 'not found' in str(error).lower() else 409 if 'locked' in str(error).lower() else 422,detail=str(error))

@router.post('/{project_id}/vector/import',status_code=201)
async def upload_vector(project_id:str,file:UploadFile=File(...),layer_id:str|None=None):
    blob=await file.read(MAX_BYTES+1);await file.close()
    try:
        parsed=await run_in_threadpool(read_vector,file.filename or '',blob)
        saved=await run_in_threadpool(commit_import,project_id,[{**parsed,'name':file.filename or 'dataset'}],layer_id,False)
        return {**saved,'driver':parsed['driver'],'source_crs':parsed['source_crs']}
    except (VectorIOError,StorageError,ValueError) as error:raise fail(error) from error

@router.get('/{project_id}/vector/export/{format_name}')
def legacy_export(project_id:str,format_name:str):
    try:
        payload,media,name=perform_export(project_id,{'format':format_name})
        return Response(payload,media_type=media,headers={'Content-Disposition':f'attachment; filename="{name}"'})
    except (VectorIOError,StorageError,ValueError) as error:raise fail(error) from error

@router.post('/{project_id}/vector/uploads',status_code=201)
async def stage_uploads(project_id:str,files:list[UploadFile]=File(...)):
    try:
        with _connect() as c:_required_project(c,project_id)
    except StorageError as error:raise fail(error) from error
    if not 1<=len(files)<=20:raise HTTPException(422,'Select 1–20 files.')
    from .exchange import cleanup_exchange,exchange_size
    await run_in_threadpool(cleanup_exchange,project_id)
    used=await run_in_threadpool(exchange_size,project_id)
    identifier=str(uuid4());path=stage_path(project_id,identifier);path.mkdir(parents=True)
    manifest=[];total=0
    try:
        for upload in files:
            file_id=str(uuid4());size=0
            with (path/file_id).open('wb') as out:
                while data:=await upload.read(1024*1024):
                    size+=len(data);total+=len(data)
                    if total+used>2*1024**3:raise VectorIOError('Project exchange storage exceeds 2 GB; discard old uploads before continuing.')
                    if size>MAX_BYTES or total>512*1024*1024:raise VectorIOError('Each file is limited to 128 MB; a batch to 512 MB.')
                    out.write(data)
            await upload.close()
            if not size:raise VectorIOError('Empty files cannot be imported.')
            manifest.append({'id':file_id,'name':Path(upload.filename or 'dataset').name,'bytes':size})
        (path/'manifest.json').write_text(dumps({'files':manifest}),'utf-8')
        return await run_in_threadpool(inspect_staged,project_id,identifier)
    except (ValueError,StorageError) as error:
        shutil.rmtree(path,ignore_errors=True);raise fail(error) from error
    finally:
        for upload in files:await upload.close()

@router.post('/{project_id}/vector/uploads/{upload_id}/inspect')
def inspect_again(project_id:str,upload_id:str,body:dict=Body(default_factory=dict)):
    from .exchange import staged_manifest
    from .vectorio import inspect_vector
    try:
        path,manifest=staged_manifest(project_id,upload_id)
        options=ImportOptions.model_validate(body.get('options',{})).model_dump(exclude_none=True)
        file=next((f for f in manifest['files'] if f['id']==body.get('file_id')),None)
        if not file:raise VectorIOError('Selected upload file was not found.')
        return inspect_vector(file['name'],(path/file['id']).read_bytes(),options)
    except (ValueError,StorageError) as error:raise fail(error) from error

@router.delete('/{project_id}/vector/uploads/{upload_id}',status_code=204)
def discard_upload(project_id:str,upload_id:str):
    with _connect() as c:_required_project(c,project_id)
    discard_stage(project_id,upload_id)

@router.post('/{project_id}/vector/import/jobs',status_code=202)
def import_job(project_id:str,body:BatchRequest):
    from .exchange import staged_manifest
    try:
        path,_=staged_manifest(project_id,body.upload_id)
        marker=path/'claimed'
        try:marker.open('x').close()
        except FileExistsError:raise VectorIOError('This upload already has an import job. Inspect a new batch to import again.')
        try:return queue_job(project_id,'vector_import',body.model_dump(exclude_none=True))
        except Exception:
            marker.unlink(missing_ok=True);raise
    except (ValueError,StorageError) as error:raise fail(error) from error

@router.post('/{project_id}/vector/export/preflight')
def export_preflight(project_id:str,body:ExportRequest):
    try:return preflight(project_id,body.model_dump(exclude_none=True))
    except (ValueError,StorageError) as error:raise fail(error) from error

@router.post('/{project_id}/vector/export')
def export_dataset(project_id:str,body:ExportRequest):
    try:
        payload,media,name=perform_export(project_id,body.model_dump(exclude_none=True))
        return Response(payload,media_type=media,headers={'Content-Disposition':f'attachment; filename="{name}"'})
    except (ValueError,StorageError) as error:raise fail(error) from error

@router.post('/{project_id}/vector/export/jobs',status_code=202)
def export_job(project_id:str,body:ExportRequest):
    try:
        options=body.model_dump(exclude_none=True)
        if options.get('collection') is not None:raise VectorIOError('Background exports require saved project data; use direct export for local drafts.')
        preflight(project_id,options)
        return queue_job(project_id,'vector_export',options)
    except (ValueError,StorageError) as error:raise fail(error) from error

@router.get('/{project_id}/vector/jobs/{job_id}/download')
def job_download(project_id:str,job_id:str):
    try:
        job=get_job(project_id,job_id)
        if job['status']!='completed' or job['kind'] not in {'vector_import','vector_export'}:raise VectorIOError('A completed exchange job is required.')
        result=job['result'];path,meta=get_artifact(project_id,result.get('artifact_id') or result['report_id'])
        return FileResponse(path,filename=meta['name'],media_type=meta['media'])
    except (ValueError,StorageError) as error:raise fail(error) from error

class PackageRaster(BaseModel):
    id:str
    kind:Literal['image','dem']

class PackageRequest(BaseModel):
    rasters:list[PackageRaster]=Field(default_factory=list,max_length=100)

@router.post('/{project_id}/package/export')
def export_package(project_id:str,body:PackageRequest,request:Request):
    from .project_package import build_package
    if body.rasters and getattr(request.state,'principal',None):raise HTTPException(403,'Raster packaging requires an operator credential.')
    try:
        data=build_package(project_id,[r.model_dump() for r in body.rasters])
        return Response(data,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="geofathom-project.zip"'})
    except (ValueError,StorageError,FileNotFoundError) as error:raise fail(error) from error

@router.post('/{project_id}/package/import',status_code=201)
async def import_package(project_id:str,request:Request,file:UploadFile=File(...),
                         token:str|None=Header(default=None,alias='X-GeoFathom-Admin-Token')):
    from .project_package import restore_package
    from imagery.routes import require_raster_import
    # Package restoration can install GeoTIFFs in the local catalog.
    require_raster_import(request,token)
    data=await file.read(MAX_BYTES+1);await file.close()
    if len(data)>MAX_BYTES:raise HTTPException(422,'Compressed package exceeds 128 MB.')
    try:return await run_in_threadpool(restore_package,project_id,data)
    except (ValueError,StorageError,KeyError,__import__('zipfile').BadZipFile) as error:raise fail(error) from error
