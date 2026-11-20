"""Local, bounded GeoTIFF library, with opaque IDs and no remote URL fetch."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from .raster import RasterError, metadata

_ROOT = Path(__file__).resolve().parent.parent


def imagery_dir() -> Path:
    return Path(os.getenv("GEOFATHOM_IMAGERY_DIR") or
                _ROOT / "data" / "imagery").expanduser()


def image_file(identifier: str) -> Path:
    try:
        uid = str(UUID(identifier))
        if uid != identifier:
            raise ValueError("Non-canonical identifier.")
    except (ValueError, TypeError) as error:
        raise RasterError("Invalid imagery ID.") from error
    path = imagery_dir() / f"{uid}.tif"
    if not path.is_file():
        raise FileNotFoundError("Image not found.")
    return path


def describe(identifier: str) -> dict:
    path = image_file(identifier)
    result = metadata(path)
    sidecar = path.with_suffix(".json")
    extra = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    return {**result, "id": identifier, "name": extra.get("name", identifier),
            "preview_url": f"/imagery/{identifier}/preview"}


def list_images() -> dict:
    root = imagery_dir()
    root.mkdir(parents=True, exist_ok=True)
    images = []
    for path in sorted(root.glob("*.tif"))[:100]:
        try:
            images.append(describe(path.stem))
        except (RasterError, FileNotFoundError, ValueError, json.JSONDecodeError):
            continue
    return {"images": images, "count": len(images)}


def store_upload(temp_path: Path, filename: str) -> dict:
    """Validate metadata before moving the uploaded file into the managed library."""
    metadata(temp_path)
    root = imagery_dir()
    root.mkdir(parents=True, exist_ok=True)
    if len(list(root.glob("*.tif"))) >= 100:
        raise RasterError("The local imagery catalog is full (100 files).")
    identifier = str(uuid4())
    final = root / f"{identifier}.tif"
    os.replace(temp_path, final)
    sidecar = final.with_suffix(".json")
    sidecar.write_text(json.dumps({"name": Path(filename).name[:160]}), encoding="utf-8")
    return describe(identifier)
