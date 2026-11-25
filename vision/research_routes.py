"""Operator endpoints for frozen datasets and reviewed local building checkpoints."""
import importlib.util
import os
from pathlib import Path
import tempfile
import zipfile

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from rasterio.errors import RasterioError
from imagery.raster import RasterError
from imagery.store import file_sha256
from imagery.routes import require_raster_import
from jobs.queue import get_job
from storage.database import StorageError
from .building_research_store import dataset_catalog, dataset_root, import_dataset_package, result_directory, install_training_model

router = APIRouter(tags=["building-research"])


def operator(request, token):
    if getattr(request.state, "principal", None):
        raise HTTPException(status_code=403, detail="Building study management is operator-only.")
    require_raster_import(request, token)


@router.get("/vision/buildings/research")
def catalog(request: Request, token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token")):
    operator(request, token)
    available = all(importlib.util.find_spec(name) is not None for name in ("torch", "safetensors", "segmentation_models_pytorch", "onnx"))
    try:
        return {**dataset_catalog(), "training_runtime_available": available,
                "test_policy": "Threshold, postprocessing and model selection use validation regions only."}
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/vision/buildings/datasets", status_code=201)
async def upload(request: Request, file: UploadFile = File(...),
                 token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token")):
    operator(request, token)
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Upload a frozen building dataset ZIP package.")
    root = dataset_root()
    root.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".upload-", suffix=".zip", dir=root)
    total = 0
    try:
        with os.fdopen(handle, "wb") as target:
            while block := await file.read(1024*1024):
                total += len(block)
                if total > 256*1024**2:
                    raise RasterError("Building study ZIP exceeds 256 MiB.")
                target.write(block)
        return await run_in_threadpool(import_dataset_package, Path(temporary))
    except (ValueError, OSError, RasterioError, zipfile.BadZipFile) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        Path(temporary).unlink(missing_ok=True)


@router.post("/projects/{project_id}/jobs/{job_id}/install-building-model")
def install(project_id: str, job_id: str, request: Request,
            token: str | None = Header(default=None, alias="X-GeoFathom-Admin-Token")):
    operator(request, token)
    try:
        job = get_job(project_id, job_id)
        if job["kind"] != "building_train" or job["status"] != "completed":
            raise RasterError("Select a completed building training job from this project.")
        root = result_directory(job_id)
        for name in ("model.onnx", "model.json", "model.safetensors"):
            if file_sha256(root / name) != job["result"]["artifacts"][name]["sha256"]:
                raise RasterError("Training artifact changed before installation.")
        return install_training_model(root, "local-building-"+job_id[:12])
    except (ValueError, OSError, StorageError) as error:
        raise HTTPException(status_code=404 if "not found" in str(error).lower() else 422, detail=str(error)) from error
