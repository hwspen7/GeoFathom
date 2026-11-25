"""Disk-backed immutable large terrain products, addressed by SHA-256."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import hashlib
import os
import re
from threading import RLock

from imagery.raster import RasterError
from imagery.store import imagery_dir
from .cancellation import checkpoint

_lock=RLock()
_MAX_BYTES=20*1024**3
_MAX_FILES=256


def root():
    return imagery_dir()/".terrain-products"


def product_path(identifier):
    if not isinstance(identifier,str) or re.fullmatch(r"[0-9a-f]{64}",identifier) is None:
        raise RasterError("Invalid terrain product ID.")
    path=root()/(identifier+".tif")
    if not path.is_file():raise FileNotFoundError("Terrain product is unavailable.")
    return path


@contextmanager
def temporary_product(cells):
    directory=root();directory.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(directory).free < cells*8+128*1024**2:
        raise RasterError("Insufficient disk space for scientific raster export.")
    with tempfile.NamedTemporaryFile(dir=directory,prefix=".writing-",suffix=".tif",delete=False) as stream:
        path=Path(stream.name)
    try:yield path
    finally:path.unlink(missing_ok=True)


def publish(path,cancel=None):
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            checkpoint(cancel)
            block=stream.read(1024*1024)
            if not block:break
            digest.update(block)
    identifier=digest.hexdigest()
    final=root()/(identifier+".tif")
    with _lock:
        if not final.exists():
            files=list(root().glob("[0-9a-f]*.tif"))
            if len(files)>=_MAX_FILES or sum(p.stat().st_size for p in files)+path.stat().st_size>_MAX_BYTES:
                raise RasterError("Scientific raster storage is full. Export and remove unneeded products.")
            os.replace(path,final)
    return identifier


def remove(identifier):
    with _lock:product_path(identifier).unlink()

def list_products():
    with _lock:
        items=[]
        for path in sorted(root().glob("*.tif")):
            if re.fullmatch(r"[0-9a-f]{64}",path.stem) is None:continue
            stat=path.stat()
            items.append({"id":path.stem,"bytes":stat.st_size,"modified":stat.st_mtime})
        return {"products":items,"total_bytes":sum(item["bytes"] for item in items),"limit_bytes":_MAX_BYTES,"limit_files":_MAX_FILES}
