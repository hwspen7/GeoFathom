"""Prepare a frozen city-disjoint building study from original PolyTopoBench data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely import from_wkb
from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from imagery.store import file_sha256
from vision.building_dataset import freeze_dataset

SOURCE = "https://huggingface.co/datasets/PingL/PolyTopoBench"
REVISION = "91319835ea7fcbdad25105cbe90af58258259250"
ANNOTATIONS = {
    "train.parquet": "bba356e5467bf382313846f378a77413ead71b429b86630c93fd320d180243ea",
    "val.parquet": "5b0a0182990ea3fa9adf15c38d8e456e23e4ad1218055698f6807e0bf17204ac",
}
INDEX_SHA256 = "4236e9660525ce3f2f2b82d4660238f5a83fb357f60c0911822a9d81f0fa4ed5"
CITY_ROLES = {"austin": "train", "vienna": "train", "chicago": "validation",
              "kitsap": "test", "tyrol-w": "test"}


def download(relative, destination, expected=None, limit=32*1024**2):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        stage = destination.with_suffix(destination.suffix+".part")
        try:
            with urlopen(f"{SOURCE}/resolve/{REVISION}/{relative}", timeout=60) as inp, stage.open("wb") as out:
                count = 0
                while block := inp.read(1024*1024):
                    count += len(block)
                    if count > limit:
                        raise ValueError("Public building source exceeded its download allowance.")
                    out.write(block)
            if expected and file_sha256(stage) != expected:
                raise ValueError("Public annotation SHA-256 mismatch.")
            stage.replace(destination)
        finally:
            stage.unlink(missing_ok=True)
    if expected and file_sha256(destination) != expected:
        raise ValueError("Cached building source SHA-256 mismatch.")
    return destination


def prepare(root, train_per_city=24, evaluation_per_city=8):
    import pyarrow.parquet as pq
    root = Path(root).resolve()
    if (root / "dataset.json").exists():
        raise ValueError("Study is frozen already; choose a fresh output directory.")
    root.mkdir(parents=True, exist_ok=True)
    index = download("inria/splits.csv", root / "source/splits.csv", INDEX_SHA256)
    rows = list(csv.DictReader(index.open(encoding="utf-8")))
    chosen = []
    for city, role in CITY_ROLES.items():
        count = train_per_city if role == "train" else evaluation_per_city
        # Deterministic selection uses source identities only, never mask contents.
        pool = sorted([r for r in rows if r["city"] == city],
                      key=lambda r: hashlib.sha256(("geofathom-city-study-731:"+r["file_name"]).encode()).hexdigest())
        groups = set()
        selected = []
        for row in pool:
            if row["source_tile"] not in groups:
                selected.append(row)
                groups.add(row["source_tile"])
            if len(selected) == count:
                break
        if len(selected) != count:
            raise ValueError("Not enough distinct source scenes in a study city.")
        chosen.extend(selected)
    lookup = {(r["split"], r["file_name"]): r for r in chosen}
    polygons = {key: [] for key in lookup}
    for split in ("train", "val"):
        file = download(f"inria/building/{split}.parquet", root / f"source/{split}.parquet", ANNOTATIONS[split+".parquet"])
        parquet = pq.ParquetFile(file)
        for batch in parquet.iter_batches(batch_size=4096, columns=["file_name", "geometry"]):
            for row in batch.to_pylist():
                key = (split, row["file_name"])
                if key in polygons:
                    geometry = from_wkb(row["geometry"])
                    if geometry.is_empty or not geometry.is_valid:
                        raise ValueError("Selected reference polygon is invalid; source labels remain unchanged.")
                    polygons[key].append(geometry)

    def obtain(row):
        relative = f"inria/images/{row['split']}/{row['file_name']}"
        return download(relative, root / "images" / row["file_name"], limit=4*1024**2)
    with ThreadPoolExecutor(max_workers=6) as pool:
        images = list(pool.map(obtain, chosen))
    samples = []
    for row, image in zip(chosen, images):
        relative = Path(row["file_name"])
        labels = root / "labels" / relative
        instances = root / "instances" / relative
        labels.parent.mkdir(parents=True, exist_ok=True)
        instances.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(image) as src:
            # The publisher intentionally uses pixel coordinates; no geographic CRS is fabricated.
            if src.crs is not None or not src.transform.is_identity:
                raise ValueError("Published patch coordinate contract changed; review provenance before conversion.")
            geometries = polygons[(row["split"], row["file_name"])]
            ids = rasterize([(mapping(g), i+1) for i, g in enumerate(geometries)], out_shape=src.shape,
                            transform=Affine.identity(), fill=0, dtype="int32") if geometries else np.zeros(src.shape, np.int32)
            profile = dict(driver="GTiff", width=src.width, height=src.height,
                           count=1, transform=Affine.identity(), compress="deflate")
            with rasterio.open(labels, "w", dtype="uint8", **profile) as dst:
                dst.write((ids > 0).astype(np.uint8), 1)
            with rasterio.open(instances, "w", dtype="int32", **profile) as dst:
                dst.write(ids, 1)
        sample = {"id": relative.stem, "region": row["city"], "group": row["source_tile"],
            "split": CITY_ROLES[row["city"]], "coordinate_space": "pixel",
            "image": str(image.relative_to(root)), "labels": str(labels.relative_to(root)),
            "instances": str(instances.relative_to(root)),
            "source_split": row["split"], "source_file": row["file_name"],
            "pixel_origin": [int(row["x0"]), int(row["y0"])], "ground_sampling_distance_m": .3}
        for key, path in (("image", image), ("labels", labels), ("instances", instances)):
            sample[key+"_sha256"] = file_sha256(path)
        samples.append(sample)
    return freeze_dataset(root, samples, provenance={"dataset": SOURCE, "revision": REVISION,
        "annotation_sha256": ANNOTATIONS, "index_sha256": file_sha256(index),
        "sampling": "SHA-256 order seeded 731; one patch per source scene; labels not consulted",
        "split_policy": CITY_ROLES, "georeferencing": "Pixel coordinates only; no geographic area claim.",
        "annotation_policy": "Author WKB rings retain holes; last annotation wins on overlapping raster pixels.",
        "limitations": "Small cross-city study. Publisher removed empty patches from its train subset; source sampling reflects that availability.",
        "attribution": "Inria imagery: Maggiori et al. (2017). PolyTopoBench curation: Liu et al. (2026). Vector labels: OpenStreetMap contributors, ODbL-1.0."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-per-city", type=int, default=24)
    parser.add_argument("--evaluation-per-city", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.train_per_city <= 36 or not 1 <= args.evaluation_per_city <= 36:
        raise SystemExit("Choose 1–36 distinct source scenes per city.")
    print(prepare(args.output, args.train_per_city, args.evaluation_per_city))


if __name__ == "__main__":
    main()
