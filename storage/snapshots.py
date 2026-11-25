"""Private, byte-verified execution snapshots for imagery and model inputs.

Copies are bounded and job-local; no mutable catalog path is read after
capture. A snapshot represents the files available at execution start,
not a database-wide historical revision at queue-submission time.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

_image_paths=ContextVar("snapshot_image_paths",default=None)
_model_root=ContextVar("snapshot_model_root",default=None)


def image_override(identifier):
    paths=_image_paths.get()
    return paths.get(identifier) if paths else None


def model_override():
    return _model_root.get()


def _identity(path):
    stat=path.stat()
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)


def copy_verified(source,destination):
    """Capture exact bytes and reject changes during the source read."""
    source=Path(source)
    before=_identity(source)
    digest=hashlib.sha256()
    count=0
    with source.open("rb") as inp,destination.open("xb") as out:
        while True:
            block=inp.read(1024*1024)
            if not block:
                break
            count+=len(block)
            if count>before[2]:
                raise RuntimeError("Snapshot source changed during capture.")
            digest.update(block)
            out.write(block)
    if count!=before[2] or _identity(source)!=before:
        raise RuntimeError("Snapshot source changed during capture.")
    return digest.hexdigest()


@contextmanager
def analysis_snapshot(kind,payload):
    """Snapshot only local inputs; remote assets need versioned object IDs."""
    from imagery.store import image_file
    from vision.semantic import model_directory,_manifest
    from storage.database import StorageError
    identifiers=[payload["image_id"]]
    if kind=="spectral_change":
        identifiers.append(payload["after_image_id"])
    originals={uid:image_file(uid) for uid in identifiers}
    models={}
    if kind in {"semantic_segmentation","building_extraction"}:
        config=_manifest(payload["model_id"])
        model=config["model_path"]
        models={model.name:model,model.with_suffix(".json").name:model.with_suffix(".json")}
    root=Path(os.getenv("GEOFATHOM_SNAPSHOT_DIR") or
              os.getenv("GEOFATHOM_RASTER_TEMP_DIR") or __import__("tempfile").gettempdir())
    root.mkdir(parents=True,exist_ok=True)
    budget=int(os.getenv("GEOFATHOM_SNAPSHOT_LIMIT_MB","16384"))
    if not 64<=budget<=32768:
        raise StorageError("Snapshot budget must be 64–32768 MiB.")
    size=sum(p.stat().st_size for p in [*originals.values(),*models.values()])
    if size>budget*1024*1024 or shutil.disk_usage(root).free<size+32*1024*1024:
        raise StorageError("Not enough snapshot disk budget or free disk space.")
    with TemporaryDirectory(prefix="geofathom-snapshot-",dir=root) as directory:
        base=Path(directory)
        paths={}
        hashes={}
        expected={source:_identity(source) for source in [*originals.values(),*models.values()]}
        for uid,source in originals.items():
            target=base/(uid+".tif")
            hashes[uid]=copy_verified(source,target)
            paths[uid]=target
        model_hashes={}
        for name,source in models.items():
            model_hashes[name]=copy_verified(source,base/name)
        # Check the entire capture interval, including related model manifests.
        if any(_identity(source)!=identity for source,identity in expected.items()):
            raise StorageError("Analysis inputs changed during snapshot capture.")
        image_token=_image_paths.set(paths)
        model_token=_model_root.set(base if models else None)
        try:
            yield {"source_sha256":hashes,"model_files_sha256":model_hashes,
                   "snapshot":"private-execution-copy",
                   "task_kind":kind}
        finally:
            _model_root.reset(model_token)
            _image_paths.reset(image_token)
