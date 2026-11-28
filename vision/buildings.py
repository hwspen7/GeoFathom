"""Native-grid building extraction with bounded inference and geographic outputs."""
from contextlib import ExitStack
import csv
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from uuid import UUID
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from rasterio.windows import Window

from geometry.measure import measure_geometry
from imagery.raster import RasterError, _check
from imagery.store import file_sha256
from .semantic import _manifest, _predict_tile, predict_building_heads, fuse_building_heads
from .tiles import context_tiles
from .tiled import TilePlan, _tile_bands, _disk_features, _check_scratch
from .runtime import tensor_budget_mb


class BuildingInput(BaseModel):
    # A task has one reproducible parameter set; unknown switches are rejected.
    model_config = ConfigDict(extra="forbid", strict=True)
    image_id: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=64)
    probability_threshold: float = Field(default=.5, gt=0, lt=1, allow_inf_nan=False)
    minimum_area_m2: float = Field(default=4., ge=0, le=100000, allow_inf_nan=False)
    minimum_pixels: int = Field(default=9, ge=1, le=10000)
    max_features: int = Field(default=100, ge=1, le=100)
    max_pixels: int = Field(default=16_777_216, ge=1, le=400_000_000)
    memory_mb: int = Field(default=64, ge=16, le=512)
    aoi: dict | None = None
    full_resolution: bool = True
    instance_mode: Literal["connected", "watershed"] = "connected"
    seed_distance: int = Field(default=6, ge=1, le=64)
    boundary_weight: float = Field(default=1., ge=0, le=4, allow_inf_nan=False)
    augmentation: Literal["none", "flips"] = "none"


def validate(payload):
    options = BuildingInput.model_validate(payload)
    if not options.full_resolution:
        raise RasterError("Building extraction requires native pixel resolution.")
    if options.aoi is not None:
        measure_geometry(options.aoi)
        if options.aoi.get("type") not in ("Polygon", "MultiPolygon"):
            raise RasterError("Building study area must be a polygon.")
    return options


def artifact_directory(job_id):
    # Only server-issued job identifiers select artifact directories.
    if not isinstance(job_id, str) or str(UUID(job_id)) != job_id:
        raise RasterError("Invalid building task identifier.")
    root = Path(os.getenv("GEOFATHOM_BUILDING_RESULTS_DIR") or
                Path(__file__).resolve().parents[1] / "data" / "building-results")
    return root.resolve() / job_id


def _figure(features, destination):
    from matplotlib.figure import Figure
    areas = [f["properties"]["area_m2"] for f in features]
    fig = Figure(figsize=(7.2, 3.2), layout="constrained")
    ax = fig.subplots()
    if areas:
        ax.hist(areas, bins=min(20, max(1, math.ceil(math.sqrt(len(areas))))),
                color="0.75", edgecolor="black", linewidth=.6)
    else:
        ax.text(.5, .5, "No retained building candidates", ha="center", va="center",
                transform=ax.transAxes)
    ax.set(xlabel="Estimated footprint area (m²)", ylabel="Candidate regions",
           title="Building footprint area distribution")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(destination, dpi=220)


def _region_probability(feature, source_crs, probability):
    """Accumulate probabilities with fixed-size reads, including polygon holes."""
    geom = transform_geom("EPSG:4326", source_crs, feature["geometry"])
    window = geometry_window(probability, [geom]).intersection(
        Window(0, 0, probability.width, probability.height))
    total = 0.
    count = 0
    for y in range(int(window.row_off), int(window.row_off + window.height), 256):
        for x in range(int(window.col_off), int(window.col_off + window.width), 256):
            block = Window(x, y, min(256, probability.width - x),
                           min(256, probability.height - y))
            data = probability.read(1, window=block)
            inside = geometry_mask([geom], data.shape,
                probability.window_transform(block), invert=True)
            usable = inside & (data >= 0)
            total += float(data[usable].astype(np.float64).sum())
            count += int(usable.sum())
    return total / count if count else None


def extract_buildings(path, options, output_dir, progress=None, cancelled=None):
    """Persist a binary mask, probabilities, WGS84 footprints and an area figure.

    Connected foreground regions are candidates, not verified building instances.
    No corner squaring or hole filling silently changes the measured footprints.
    """
    options = validate(options) if isinstance(options, dict) else options
    config = _manifest(options.model_id)
    if (config["task"] != "building_extraction" or config["classes"] != ["background", "building"]
            or config["output_type"] not in ("binary_logits", "binary_probability")):
        raise RasterError("Select a building model declaring background and building classes.")
    device = os.getenv("GEOFATHOM_VISION_DEVICE", "cpu").lower()
    if device not in ("cpu", "cuda"):
        raise RasterError("Vision device must be cpu or cuda.")
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise RasterError("Building task artifacts already exist; submit a new task.")
    started = time.monotonic()

    def tick(fraction):
        if cancelled is not None:
            cancelled()
        if progress is not None:
            progress(fraction)

    with TemporaryDirectory(prefix="."+output_dir.name+"-", dir=output_dir.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        with rasterio.open(path) as src:
            _check(src)
            if max(config["bands"]) > src.count:
                raise RasterError("The source image lacks the building model's RGB bands.")
            # Preserve the original pixel grid while cropping the inference extent.
            roi = None
            crop = Window(0, 0, src.width, src.height)
            if options.aoi is not None:
                try:
                    roi = transform_geom("EPSG:4326", str(src.crs), options.aoi)
                    crop = geometry_window(src, [roi])
                except rasterio.errors.WindowError as error:
                    raise RasterError("The study area does not overlap the source image.") from error
                except Exception as error:
                    raise RasterError("The study area cannot overlap or be projected into the source CRS.") from error
            width, height = int(crop.width), int(crop.height)
            affine = src.window_transform(crop)
            plan = TilePlan(width, height, config["tile_size"], options.max_pixels,
                            options.memory_mb)
            needed = plan.tile_size**2 * (len(config["bands"]) +
                     4 * max(2, config["output_channels"]) + 12) * 4
            if needed > min(options.memory_mb, tensor_budget_mb()) * 1024**2:
                raise RasterError("Building model exceeds the per-tile tensor allowance.")
            # Probabilities plus mask need five uncompressed bytes per pixel.
            import shutil
            quota_mb = int(os.getenv("GEOFATHOM_BUILDING_ARTIFACT_MB", "512"))
            quota = quota_mb * 1024**2
            # Watershed may retain two auxiliary fields and a 32-bit instance grid.
            bytes_per_pixel = 17 if options.instance_mode == "watershed" else 5
            if not 16 <= quota_mb <= 4096 or width * height * bytes_per_pixel + 8 * 1024**2 > quota:
                raise RasterError("Building artifact budget is insufficient for this study area.")
            if shutil.disk_usage(stage).free < width * height * bytes_per_pixel + 32 * 1024**2:
                raise RasterError("Insufficient disk space for building outputs.")
            profile = dict(driver="GTiff", width=width, height=height, count=1,
                           crs=src.crs, transform=affine, tiled=True,
                           blockxsize=128, blockysize=128, compress="deflate")
            halo = config["halo"]
            stride = plan.tile_size - 2 * halo
            tile_count = math.ceil(width / stride) * math.ceil(height / stride)
            mean = np.asarray(config["mean"], np.float32)[:, None, None]
            std = np.asarray(config["std"], np.float32)[:, None, None]
            valid_pixels = foreground_pixels = 0
            with ExitStack() as stack:
                mask = stack.enter_context(rasterio.open(stage / "mask.tif", "w",
                    **profile, dtype="uint8", nodata=255))
                probability = stack.enter_context(rasterio.open(stage / "probability.tif", "w",
                    **profile, dtype="float32", nodata=-1.))
                auxiliary = {}
                if options.instance_mode == "watershed":
                    for name in ("boundary", "distance"):
                        if config.get(name+"_channel") is not None:
                            auxiliary[name] = stack.enter_context(rasterio.open(stage / (name+".tif"), "w",
                                **profile, dtype="float32", nodata=-9999.))
                for number, tile in enumerate(context_tiles(width, height, plan.tile_size, halo)):
                    tick(.8 * number / tile_count)
                    # Context comes from the original scene even when the AOI crops its
                    # output extent; an AOI edge must not invent a new image boundary.
                    top = int(crop.row_off + tile.core.row_off) - halo
                    left = int(crop.col_off + tile.core.col_off) - halo
                    start_y, start_x = max(0, top), max(0, left)
                    source_window = Window(start_x, start_y,
                        min(src.width, left + plan.tile_size) - start_x,
                        min(src.height, top + plan.tile_size) - start_y)
                    raw, valid = _tile_bands(src, config["bands"], source_window)
                    if np.any(raw[:, valid] < 0) or np.any(raw[:, valid] > config["input_scale"]):
                        raise RasterError("Source pixel range exceeds the model input scale; use the expected RGB encoding.")
                    # Reflect scene-edge context rather than inventing black image borders.
                    rows, cols = valid.shape
                    y, x = start_y - top, start_x - left
                    pad = ((0, 0), (y, plan.tile_size - rows - y),
                           (x, plan.tile_size - cols - x))
                    normalized = (np.nan_to_num(raw, nan=0., posinf=0., neginf=0.) /
                                  config["input_scale"] - mean) / std
                    tensor = np.pad(normalized, pad, mode="edge")[None].astype(np.float32)
                    if options.augmentation != "none":
                        heads = fuse_building_heads(tensor, config, device, augmentation=options.augmentation)
                        scores = heads["probability"][tile.crop]
                    elif options.instance_mode == "watershed":
                        heads = predict_building_heads(tensor, config, device)
                        scores = heads["probability"][tile.crop]
                    else:
                        labels, confidence = _predict_tile(tensor, config, device)
                        if labels.shape != (plan.tile_size, plan.tile_size):
                            raise RasterError("Building model output grid does not match its input.")
                        scores = np.where(labels == 1, confidence, 1 - confidence)[tile.crop]
                    core_valid = valid[halo-y:halo-y+int(tile.core.height),
                                       halo-x:halo-x+int(tile.core.width)].copy()
                    if roi is not None:
                        core_valid &= geometry_mask([roi], scores.shape,
                            rasterio.windows.transform(tile.core, affine), invert=True)
                    if (not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1))):
                        raise RasterError("Building model returned invalid probabilities.")
                    positive = core_valid & (scores >= options.probability_threshold)
                    mask.write(np.where(core_valid, positive, 255).astype(np.uint8),
                               1, window=tile.core)
                    probability.write(np.where(core_valid, scores, -1).astype(np.float32),
                                      1, window=tile.core)
                    for name, target in auxiliary.items():
                        target.write(np.where(core_valid, heads[name][tile.crop], -9999).astype(np.float32),
                                     1, window=tile.core)
                    valid_pixels += int(core_valid.sum())
                    foreground_pixels += int(positive.sum())
            if not valid_pixels:
                raise RasterError("The study area contains no valid source pixels.")
            for name in ("mask.tif", "probability.tif"):
                _check_scratch(stage / name, quota)
            vector_source, classes, instance_summary = stage / "mask.tif", {1: "building"}, None
            if options.instance_mode == "watershed":
                from .building_instances import instance_raster, InstanceClasses
                vector_source = stage / "instances.tif"
                instance_summary = instance_raster(stage / "mask.tif", stage / "probability.tif", vector_source,
                    boundary_path=stage / "boundary.tif" if "boundary" in auxiliary else None,
                    distance_path=stage / "distance.tif" if "distance" in auxiliary else None,
                    seed_distance=options.seed_distance, boundary_weight=options.boundary_weight,
                    memory_mb=options.memory_mb, progress=lambda _: tick(.84))
                classes = InstanceClasses()
            features, truncated = _disk_features(vector_source, classes,
                options.max_features, options.minimum_pixels, progress=lambda _: tick(.85))
            retained = []
            with rasterio.open(stage / "probability.tif") as probability:
                for feature in features:
                    tick(.9)
                    measurement = measure_geometry(feature["geometry"])
                    if measurement["area_m2"] < options.minimum_area_m2:
                        continue
                    props = feature["properties"]
                    if instance_summary is not None:
                        props["instance_id"] = props["class_id"]
                        props["class_id"] = 1
                    props.update({"image_id": options.image_id, "model_id": options.model_id,
                        "provider": "onnxruntime", "method": "building_extraction",
                        "probability_threshold": options.probability_threshold,
                        "mean_building_probability": _region_probability(feature, str(src.crs), probability),
                        "confidence_calibrated": False,
                        "perimeter_m": measurement["perimeter_m"],
                        "compactness": 4 * math.pi * measurement["area_m2"] / measurement["perimeter_m"]**2,
                        "instance_status": "watershed_estimate_requires_review" if instance_summary else
                                           "connected_region_may_contain_touching_buildings"})
                    feature["id"] = f"building-{len(retained)+1}"
                    retained.append(feature)
            result = {"type": "FeatureCollection", "features": retained,
                "analysis": "building_extraction", "engine": "rasterio-stream+onnxruntime-" + device,
                "provider": "onnxruntime", "model_id": options.model_id,
                "source_images": [options.image_id], "source_crs": str(src.crs),
                "geometry_crs": "EPSG:4326", "pixel_grid": [width, height],
                "valid_pixels": valid_pixels, "classified_pixels": foreground_pixels,
                "tile_count": tile_count, "context_halo": halo, "truncated": truncated,
                "inference_passes_per_tile": 4 if options.augmentation == "flips" else 1,
                "confidence_calibrated": False, "parameters": options.model_dump(),
                "instance_separation": instance_summary,
                "summary": {"candidate_count": len(retained),
                    "total_area_m2": sum(f["properties"]["area_m2"] for f in retained),
                    "foreground_fraction": foreground_pixels / valid_pixels},
                "model_sha256": file_sha256(config["model_path"]),
                "image_sha256": file_sha256(Path(path)),
                "manifest_sha256": file_sha256(config["model_path"].with_suffix(".json")),
                "seconds": round(time.monotonic() - started, 3),
                "warning": "Image-derived building candidates require review. Touching buildings may form "
                           "one region; roof outlines can differ from ground footprints. Probabilities are uncalibrated."}
        # Publish all artifacts together only after inference, vectorization and cancellation checks.
        (stage / "footprints.geojson").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        with (stage / "footprints.csv").open("w", newline="", encoding="utf-8") as out:
            fields = ["building_id", "area_m2", "perimeter_m", "mean_building_probability", "compactness", "pixel_count"]
            writer = csv.writer(out)
            writer.writerow(fields)
            for feature in retained:
                writer.writerow([feature["id"], *(feature["properties"][key] for key in fields[1:])])
        _figure(retained, stage / "areas.png")
        _figure(retained, stage / "areas.svg")
        names = ["mask.tif", "probability.tif", "footprints.geojson", "footprints.csv", "areas.png", "areas.svg"]
        if instance_summary is not None:
            names.extend(["instances.tif", *(name+".tif" for name in auxiliary)])
        result["artifacts"] = {name: {"sha256": file_sha256(stage / name),
            "size_bytes": (stage / name).stat().st_size} for name in names}
        if sum(v["size_bytes"] for v in result["artifacts"].values()) > quota:
            raise RasterError("Building outputs exceed the configured artifact budget.")
        tick(1.)
        stage.replace(output_dir)
    return result
