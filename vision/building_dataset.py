"""Immutable, byte-verified building datasets with region-disjoint holdouts."""
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio

from imagery.raster import RasterError
from imagery.store import file_sha256

SCHEMA = "geofathom-building-dataset-1"
SPLITS = ("train", "validation", "test")


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def safe_relative(root, value):
    if not isinstance(value, str) or not value or len(value) > 500:
        raise RasterError("Dataset source must be a bounded relative path.")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RasterError("Dataset paths must remain inside the dataset directory.")
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise RasterError("Dataset source is missing or leaves the dataset directory.")
    return path


def audit_dataset(definition, root, *, verify_pixels=True):
    if (not isinstance(definition, dict) or definition.get("schema") != SCHEMA
            or not isinstance(definition.get("samples"), list)
            or not 3 <= len(definition["samples"]) <= 1000):
        raise RasterError("Choose a supported building dataset with 3–1000 samples.")
    rows, identities, groups, regions, hashes = [], set(), {}, {}, {}
    for row in definition["samples"]:
        if not isinstance(row, dict) or row.get("split") not in SPLITS:
            raise RasterError("Every building sample needs an explicit data split.")
        for key in ("id", "region", "group"):
            if not isinstance(row.get(key), str) or not 1 <= len(row[key]) <= 160:
                raise RasterError("Every sample needs bounded identity, region and source-group metadata.")
        if row["id"] in identities:
            raise RasterError("Duplicate building sample identifier.")
        identities.add(row["id"])
        for seen, value, message in ((groups, row["group"], "source group"), (regions, row["region"], "region")):
            if value in seen and seen[value] != row["split"]:
                raise RasterError("Building train/validation/test leakage through shared "+message+".")
            seen[value] = row["split"]
        paths = {key: safe_relative(root, row[key]) for key in ("image", "labels", "instances") if row.get(key)}
        if "image" not in paths or "labels" not in paths:
            raise RasterError("Each building sample needs an image and independent labels.")
        digests = {key: file_sha256(path) for key, path in paths.items()}
        if digests["image"] in hashes:
            raise RasterError("Duplicate image bytes cannot occur in a frozen building dataset.")
        hashes[digests["image"]] = row["split"]
        for key, digest in digests.items():
            if row.get(key+"_sha256") != digest:
                raise RasterError("Building dataset bytes differ from their frozen SHA-256: "+row["id"])
        if verify_pixels:
            with rasterio.open(paths["image"]) as image, rasterio.open(paths["labels"]) as labels:
                if (image.shape != labels.shape or image.count != 3 or labels.count != 1
                        or max(image.shape) > 2048 or min(image.shape) < 32):
                    raise RasterError("Building image/label grids must match and remain bounded.")
                values = labels.read(1, masked=True)
                if not np.isin(values.compressed(), [0, 1]).all():
                    raise RasterError("Building labels must explicitly encode background=0, building=1.")
                if (image.crs, image.transform) != (labels.crs, labels.transform):
                    raise RasterError("Building image and label georeferencing disagree.")
                if "instances" in paths:
                    with rasterio.open(paths["instances"]) as instances:
                        if (instances.shape, instances.crs, instances.transform) != (image.shape, image.crs, image.transform):
                            raise RasterError("Building instance labels have a different grid.")
                        ids = instances.read(1)
                        eligible = ~np.ma.getmaskarray(values)
                        if not np.issubdtype(ids.dtype, np.integer) or np.any(ids < 0) or not np.array_equal(
                                ids[eligible] > 0, values.data[eligible] == 1):
                            raise RasterError("Reference instances must exactly cover the labeled building pixels.")
        rows.append({**row, "paths": paths})
    counts = {split: sum(row["split"] == split for row in rows) for split in SPLITS}
    if not all(counts.values()):
        raise RasterError("Frozen building studies require train, validation and test regions.")
    # The fingerprint binds source bytes and assignments, not host-specific absolute paths.
    material = {key: value for key, value in definition.items() if key != "fingerprint"}
    fingerprint = canonical_sha(material)
    if definition.get("fingerprint") != fingerprint:
        raise RasterError("Building dataset split or provenance changed after freezing.")
    return {"fingerprint": fingerprint, "samples": rows, "counts": counts,
            "regions": {split: sorted({row["region"] for row in rows if row["split"] == split}) for split in SPLITS},
            "definition": definition}


def load_dataset(path, *, verify_pixels=True):
    path = Path(path).resolve()
    if path.stat().st_size > 2 * 1024**2:
        raise RasterError("Building dataset definition exceeds 2 MiB.")
    return audit_dataset(json.loads(path.read_text(encoding="utf-8")), path.parent, verify_pixels=verify_pixels)


def freeze_dataset(root, samples, *, provenance, filename="dataset.json"):
    definition = {"schema": SCHEMA, "provenance": provenance, "samples": samples}
    definition["fingerprint"] = canonical_sha(definition)
    audit_dataset(definition, Path(root))
    path = Path(root) / filename
    if path.exists():
        raise RasterError("Dataset definitions are immutable; choose a new dataset directory.")
    path.write_text(json.dumps(definition, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return path
