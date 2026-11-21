"""Operator-only local GeoTIFF/COG import for files larger than HTTP limits.

There is deliberately no HTTP path-accepting endpoint: callers must have
local filesystem access to the server. GDAL/Rasterio validates source data
before a copy into the managed, immutable imagery catalog.
"""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from .raster import RasterError, metadata
from .store import imagery_dir, store_upload

MAX_LOCAL_SOURCE_BYTES = 8 * 1024 * 1024 * 1024


def import_local_image(source: Path, display_name: str | None = None) -> dict:
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in (".tif",".tiff"):
        raise RasterError("Choose a local GeoTIFF or COG file.")
    size = source.stat().st_size
    if not 0 < size <= MAX_LOCAL_SOURCE_BYTES:
        raise RasterError("Local GeoTIFF exceeds the 8 GiB import limit.")
    metadata(source)
    root = imagery_dir()
    root.mkdir(parents=True,exist_ok=True)
    if source.parent.resolve()==root.resolve():
        raise RasterError("The source is already inside the managed imagery catalog.")
    if shutil.disk_usage(root).free < size + 32*1024*1024:
        raise RasterError("Insufficient disk space to import the image.")
    handle, name = tempfile.mkstemp(prefix=".import-",suffix=".tif",dir=root)
    stage=Path(name)
    try:
        with os.fdopen(handle,"wb") as target, open(source,"rb") as data:
            shutil.copyfileobj(data,target,length=1024*1024)
        if stage.stat().st_size!=size:
            raise RasterError("Image copy was incomplete.")
        return store_upload(stage,display_name or source.name)
    finally:
        stage.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(
        description="Register a local GeoTIFF/COG without a web upload")
    parser.add_argument("path",type=Path)
    parser.add_argument("--name",default=None)
    args=parser.parse_args()
    result=import_local_image(args.path,args.name)
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
