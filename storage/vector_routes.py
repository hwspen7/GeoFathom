"""GIS vector file upload and export routed through safe GDAL/OGR drivers."""

from fastapi import APIRouter,File,UploadFile,HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .vectorio import VectorIOError, read_vector, write_vector
from .workspace import add_in_layer
from .database import export_project,StorageError

router=APIRouter(prefix="/projects",tags=["vector-io"])


@router.post("/{project_id}/vector/import",status_code=201)
async def upload_vector(project_id:str,file:UploadFile=File(...),layer_id:str|None=None)->dict:
    blob=await file.read(25*1024*1024+1)
    await file.close()
    try:
        parsed=await run_in_threadpool(read_vector,file.filename or "",blob)
        saved=await run_in_threadpool(add_in_layer,project_id,parsed["features"],layer_id)
        return {**saved,"driver":parsed["driver"],"source_crs":parsed["source_crs"]}
    except (VectorIOError,StorageError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error


@router.get("/{project_id}/vector/export/{format_name}")
def export_vector(project_id:str,format_name:str)->Response:
    try:
        collection=export_project(project_id)
        payload,media,name=write_vector(collection,format_name)
        return Response(payload,media_type=media,
                        headers={"Content-Disposition":f'attachment; filename="{name}"'})
    except (VectorIOError,StorageError) as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
