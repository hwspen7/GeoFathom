"""Disk-backed full-resolution spectral classification with bounded raster tiles.

Rasterio/GDAL owns window I/O and polygonization. C++ handles per-pixel
normalized differences. The output mask is one temporary GeoTIFF, so
components crossing tile boundaries are polygonized as ONE contiguous region.
"""
from dataclasses import dataclass
from heapq import heappush, heapreplace
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
import math
import os
import shutil
import tempfile

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape
from shapely.validation import make_valid

from geometry.measure import measure_geometry, GeometryError
from geometry.spectral import normalized_difference, classify_change
from geometry.transitions import count_transitions
from imagery.raster import RasterError, _check

MAX_PIXELS = 67_108_864
MAX_COMPONENTS = 20_000
MAX_RESULTS = 100
MAX_BOUNDARY_TRANSITIONS = 1_000_000
MAX_SCRATCH_MB = 512


@contextmanager
def _scratch(plan, prefix):
    """Conservatively check free space and per-job scratch quota.

    This is not a cross-process filesystem reservation.
    """
    configured = os.getenv("GEOFATHOM_RASTER_TEMP_DIR")
    root = os.path.abspath(configured or tempfile.gettempdir())
    os.makedirs(root, exist_ok=True)
    try:
        budget = int(os.getenv("GEOFATHOM_RASTER_SCRATCH_MB", "256"))
    except ValueError as error:
        raise RasterError("Invalid raster scratch quota.") from error
    if not 16 <= budget <= MAX_SCRATCH_MB:
        raise RasterError("Raster scratch quota must be between 16 and 512 MiB.")
    needed = plan.width * plan.height * 2 + 8 * 1024 * 1024
    if needed > budget * 1024 * 1024:
        raise RasterError("Raster scratch quota is insufficient for this image.")
    if shutil.disk_usage(root).free < needed:
        raise RasterError("Insufficient free disk space for raster analysis.")
    with TemporaryDirectory(prefix=prefix, dir=root) as temp:
        yield Path(temp), budget * 1024 * 1024


def _check_scratch(path, quota_bytes):
    if path.stat().st_size > quota_bytes:
        raise RasterError("Raster output exceeded the temporary-disk quota.")


def _transitions(labels):
    # Bound highly fragmented checkerboard-like masks before raster polygonization.
    return count_transitions(labels)


@dataclass(frozen=True)
class TilePlan:
    width: int
    height: int
    tile_size: int = 256
    max_pixels: int = 16_777_216
    memory_mb: int = 32

    def __post_init__(self):
        if (any(type(value) is not int for value in (
                self.width, self.height, self.tile_size,
                self.max_pixels, self.memory_mb))
                or self.width <= 0 or self.height <= 0
                or self.tile_size not in (64, 128, 256, 512)
                or not 1 <= self.max_pixels <= MAX_PIXELS
                or not 4 <= self.memory_mb <= 512):
            raise RasterError("Invalid raster tile dimensions or memory budget.")
        if self.width * self.height > self.max_pixels:
            raise RasterError("Raster pixel count exceeds the configured streaming limit.")
        # Worst-case temporary buffers include two float bands, masks,
        # native output, classification, GDAL conversion and Python copies.
        # 64 bytes/pixel is a conservative working-set allowance, not a
        # process-wide RAM guarantee (GDAL caching is separately managed).
        if self.tile_size * self.tile_size * 64 > self.memory_mb * 1024 * 1024:
            raise RasterError("Requested tile exceeds the per-tile memory allowance.")

    @property
    def count(self):
        return (math.ceil(self.width / self.tile_size) *
                math.ceil(self.height / self.tile_size))

    def windows(self):
        for row in range(0, self.height, self.tile_size):
            for col in range(0, self.width, self.tile_size):
                yield Window(col, row, min(self.tile_size, self.width - col),
                             min(self.tile_size, self.height - row))


def _preflight_mask(src, progress):
    # Count edges across ALL processing seams before GDAL allocates shapes.
    previous=None
    total=0
    for y in range(0,src.height,128):
        chunk=src.read(1,window=Window(0,y,src.width,min(128,src.height-y)))
        total+=_transitions(chunk)
        if previous is not None:
            total+=int(np.count_nonzero(previous!=chunk[0]))
        if total>MAX_BOUNDARY_TRANSITIONS:
            raise RasterError("Raster mask is too fragmented for safe vectorization.")
        previous=chunk[-1].copy()
        if progress is not None:
            progress(.935)


def _disk_features(path, classes, max_features=MAX_RESULTS, min_pixels=9,
                   progress=None):
    """GDAL stitches connected regions across disk blocks before polygonization."""
    heap = []
    count = 0
    found = 0
    with rasterio.open(path) as src:
        _preflight_mask(src,progress)
        band = rasterio.band(src, 1)
        pixel_area = abs(src.transform.a * src.transform.e -
                         src.transform.b * src.transform.d)
        if not pixel_area or not math.isfinite(pixel_area):
            raise RasterError("Raster transform cannot be polygonized.")
        for geom, category in shapes(band, mask=band,
                                     connectivity=4, transform=src.transform):
            count += 1
            if progress is not None and count % 32 == 0:
                progress(.94)
            if count > MAX_COMPONENTS:
                raise RasterError("Too many separate components; refine the threshold.")
            klass = int(category)
            if klass not in classes:
                continue
            polygon = shape(geom)
            pixels = int(round(polygon.area / pixel_area))
            if pixels < min_pixels:
                continue
            # 4-connectivity keeps diagonal-only neighbors separate. An
            # unexpected invalid ring is repaired only when polygonal area
            # is conserved; otherwise fail rather than silently lose pixels.
            if not polygon.is_valid:
                repaired = make_valid(polygon)
                if (repaired.is_empty or not repaired.is_valid
                        or repaired.geom_type not in ("Polygon", "MultiPolygon")
                        or abs(repaired.area - polygon.area) >
                        max(pixel_area * .001, abs(polygon.area) * 1e-8)):
                    raise RasterError("Raster polygonization produced an unrepairable region.")
                polygon = repaired
            found += 1
            item = (pixels, count, klass, polygon)
            if len(heap) < max_features:
                heappush(heap, item)
            elif pixels > heap[0][0]:
                heapreplace(heap, item)
        source_crs = str(src.crs)
        xsize = min(abs(src.transform.a) + abs(src.transform.d),
                    abs(src.transform.e) + abs(src.transform.b))
    results = []
    for pixels, _, klass, polygon in sorted(heap, reverse=True):
        if pixels > 100:
            polygon = polygon.simplify(xsize * .35, preserve_topology=True)
        geom = transform_geom(source_crs, "EPSG:4326", mapping(polygon),
                              antimeridian_cutting=True, precision=8)
        try:
            area = measure_geometry(geom)["area_m2"]
        except (GeometryError, ValueError) as error:
            raise RasterError("Streamed polygon cannot be geodesically measured.") from error
        results.append({"type": "Feature", "geometry": geom, "properties": {
            "class_id": klass, "class_name": classes[klass],
            "pixel_count": pixels, "area_m2": area,
            "boundary_status": "estimated_from_imagery",
            "quality": "requires_user_review",
        }})
    return results, found > max_features


def _tile_bands(src, bands, window):
    raw = src.read(list(bands), window=window, masked=True)
    valid = ~np.any(np.ma.getmaskarray(raw), axis=0)
    values = np.ma.filled(raw.astype(np.float32), np.nan)
    values = np.asarray(values, dtype=np.float32)
    valid &= np.all(np.isfinite(values), axis=0)
    return values, valid


def spectral_index_tiled(path: Path, image_id: str, index: str,
                         first_band: int, second_band: int,
                         threshold: float = .2, tile_size: int = 256,
                         max_pixels: int = 16_777_216, memory_mb: int = 32,
                         progress=None):
    if index not in ("ndvi", "ndwi"):
        raise RasterError("Supported indices are NDVI and NDWI.")
    if first_band == second_band:
        raise RasterError("Spectral bands must be distinct.")
    if not math.isfinite(threshold) or not -1 < threshold < 1:
        raise RasterError("Spectral threshold must be between -1 and 1.")
    with rasterio.open(path) as src:
        _check(src)
        if not all(type(b) is int and 1 <= b <= src.count
                   for b in (first_band, second_band)):
            raise RasterError("Selected spectral bands are unavailable.")
        plan = TilePlan(src.width, src.height, tile_size, max_pixels, memory_mb)
        classes = {1: "vegetation_candidate" if index == "ndvi"
                   else "surface_water_candidate"}
        acquired = (src.tags().get("ACQUISITION_DATE") or
                    src.tags().get("TIFFTAG_DATETIME"))
        crs = str(src.crs)
        valid_pixels = classified_pixels = 0
        transitions = 0
        engine = None
        with _scratch(plan, "geofathom-spectral-") as (temp, scratch_quota):
            destination = temp / "classification.tif"
            with rasterio.open(destination, "w", driver="GTiff",
                               width=src.width, height=src.height,
                               count=1, dtype="uint8", crs=src.crs,
                               transform=src.transform, nodata=0,
                               tiled=True, blockxsize=128, blockysize=128,
                               compress="deflate") as target:
                for number, window in enumerate(plan.windows(), 1):
                    if progress is not None:
                        progress((number - 1) / plan.count)
                    values, validity = _tile_bands(
                        src, (first_band, second_band), window)
                    ratios, accepted, running_engine = normalized_difference(
                        values[0], values[1], validity)
                    if engine is None:
                        engine = running_engine
                    elif engine != running_engine:
                        engine = "mixed-native-fallback"
                    labels = (accepted & (ratios >= threshold)).astype(np.uint8)
                    transitions += _transitions(labels)
                    if transitions > MAX_BOUNDARY_TRANSITIONS:
                        raise RasterError("Raster mask is too fragmented for safe vectorization.")
                    target.write(labels, 1, window=window)
                    if number % 16 == 0:
                        _check_scratch(destination, scratch_quota)
                    valid_pixels += int(accepted.sum())
                    classified_pixels += int(labels.sum())
            _check_scratch(destination, scratch_quota)
            if progress is not None:
                progress(.93)
            features, truncated = _disk_features(
                destination, classes, progress=progress)
        if progress is not None:
            progress(1.)
    for feature in features:
        feature["properties"].update({
            "image_id": image_id, "method": index,
            "bands": [first_band, second_band], "threshold": threshold})
    return {"type": "FeatureCollection", "features": features,
            "analysis": index, "engine": "rasterio-stream+" + (engine or "none"),
            "provider": "deterministic", "model_id": None,
            "source_images": [image_id], "acquired_at": acquired,
            "source_crs": crs, "geometry_crs": "EPSG:4326",
            "pixel_grid": [plan.width, plan.height],
            "valid_pixels": valid_pixels, "classified_pixels": classified_pixels,
            "tile_count": plan.count, "tile_size": tile_size,
            "memory_budget_mb": memory_mb, "truncated": truncated,
            "warning": "Full-resolution spectral extraction is deterministic, "
                       "not semantic object recognition. Check source bands and "
                       "ground resolution before accepting the polygons."}


def spectral_change_tiled(before_path: Path, after_path: Path,
                          before_id: str, after_id: str,
                          first_band: int, second_band: int,
                          threshold: float = .2, tile_size: int = 256,
                          max_pixels: int = 16_777_216, memory_mb: int = 32,
                          progress=None):
    if before_id == after_id:
        raise RasterError("Select two different dated rasters.")
    if first_band == second_band:
        raise RasterError("Spectral bands must be distinct.")
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise RasterError("Change threshold must be between zero and one.")
    with rasterio.open(before_path) as before, rasterio.open(after_path) as after:
        _check(before)
        _check(after)
        if not all(type(b) is int and 1 <= b <= min(before.count, after.count)
                   for b in (first_band, second_band)):
            raise RasterError("Both rasters must contain the selected bands.")
        plan = TilePlan(before.width, before.height,
                        tile_size, max_pixels, memory_mb)
        crs = str(before.crs)
        dates = [
            before.tags().get("ACQUISITION_DATE") or before.tags().get("TIFFTAG_DATETIME"),
            after.tags().get("ACQUISITION_DATE") or after.tags().get("TIFFTAG_DATETIME"),
        ]
        valid_pixels = gain_pixels = loss_pixels = 0
        transitions = 0
        engine = None
        with _scratch(plan, "geofathom-change-") as (temp, scratch_quota):
            output = temp / "changes.tif"
            with WarpedVRT(after, crs=before.crs, transform=before.transform,
                           width=before.width, height=before.height,
                           resampling=Resampling.bilinear) as aligned:
                with rasterio.open(output, "w", driver="GTiff",
                                   width=before.width, height=before.height,
                                   count=1, dtype="uint8", crs=before.crs,
                                   transform=before.transform, nodata=0,
                                   tiled=True, blockxsize=128, blockysize=128,
                                   compress="deflate") as target:
                    for number, window in enumerate(plan.windows(), 1):
                        if progress is not None:
                            progress((number - 1) / plan.count)
                        old, old_valid = _tile_bands(
                            before, (first_band, second_band), window)
                        new, new_valid = _tile_bands(
                            aligned, (first_band, second_band), window)
                        old_index, ov, before_engine = normalized_difference(
                            old[0], old[1], old_valid)
                        new_index, nv, after_engine = normalized_difference(
                            new[0], new[1], new_valid)
                        labels, current_engine = classify_change(
                            old_index, ov, new_index, nv, threshold)
                        if engine is None:
                            engine = current_engine
                        elif engine != current_engine:
                            engine = "mixed-native-fallback"
                        transitions += _transitions(labels)
                        if transitions > MAX_BOUNDARY_TRANSITIONS:
                            raise RasterError("Raster mask is too fragmented for safe vectorization.")
                        target.write(labels, 1, window=window)
                        if number % 16 == 0:
                            _check_scratch(output, scratch_quota)
                        valid_pixels += int((ov & nv).sum())
                        gain_pixels += int((labels == 1).sum())
                        loss_pixels += int((labels == 2).sum())
            if not valid_pixels:
                raise RasterError("The dated rasters have no valid overlapping pixels.")
            _check_scratch(output, scratch_quota)
            if progress is not None:
                progress(.93)
            features, truncated = _disk_features(
                output, {1: "index_gain", 2: "index_loss"},
                progress=progress)
        if progress is not None:
            progress(1.)
    for feature in features:
        feature["properties"].update({
            "before_image_id": before_id, "after_image_id": after_id,
            "method": "normalized_difference_change",
            "bands": [first_band, second_band], "threshold": threshold,
        })
    return {"type": "FeatureCollection", "features": features,
            "analysis": "spectral_change",
            "engine": "rasterio-stream-warped-vrt+" + (engine or "none"),
            "provider": "deterministic", "model_id": None,
            "source_images": [before_id, after_id], "acquired_at": dates,
            "source_crs": crs, "geometry_crs": "EPSG:4326",
            "pixel_grid": [plan.width, plan.height],
            "valid_pixels": valid_pixels, "gain_pixels": gain_pixels,
            "loss_pixels": loss_pixels, "tile_count": plan.count,
            "tile_size": tile_size, "memory_budget_mb": memory_mb,
            "truncated": truncated,
            "warning": "Full-resolution spectral change is not proof of land-use "
                       "change. Review radiometry, alignment, clouds and season."}


def semantic_segmentation_tiled(path: Path, image_id: str,
                                model_id: str, minimum_confidence: float = .55,
                                max_pixels: int = 16_777_216,
                                memory_mb: int = 32, progress=None):
    """Disk-backed ONNX classification over the source pixel grid.

    Optional model-declared context halos are inferred but only the disjoint
    cores are retained. This reduces, but cannot guarantee elimination of,
    model edge artifacts.
    """
    import os
    from .tiles import context_tiles
    from geometry.buffers import ScratchPool
    from .semantic import _manifest, _predict_tile, _predict_batch
    from .runtime import tensor_budget_mb
    from itertools import islice
    if (not math.isfinite(minimum_confidence)
            or not 0 <= minimum_confidence <= 1):
        raise RasterError("Confidence threshold must be between zero and one.")
    config = _manifest(model_id)
    device = os.getenv("GEOFATHOM_VISION_DEVICE", "cpu").lower()
    if device not in ("cpu", "cuda"):
        raise RasterError("Vision device must be cpu or cuda.")
    mean = np.asarray(config["mean"], dtype=np.float32)[:, None, None]
    std = np.asarray(config["std"], dtype=np.float32)[:, None, None]
    with rasterio.open(path) as src:
        _check(src)
        if max(config["bands"]) > src.count:
            raise RasterError("The raster lacks one or more model input bands.")
        plan = TilePlan(src.width, src.height, config["tile_size"],
                        max_pixels, memory_mb)
        # Model logits may require far more memory than spectral masks.
        # Account for output class channels as well as the input tensor.
        bytes_needed = (plan.tile_size * plan.tile_size *
                        (len(config["bands"]) + 4 * len(config["classes"]) + 12) * 4)
        budget = min(memory_mb, tensor_budget_mb()) * 1024 * 1024
        batch_size = min(config.get("max_batch",1), budget // bytes_needed)
        if batch_size < 1:
            raise RasterError("Model output tensors exceed the per-tile memory allowance.")
        halo = config.get("halo", 0)
        stride = plan.tile_size - 2 * halo
        tile_count = math.ceil(src.width / stride) * math.ceil(src.height / stride)
        crs = str(src.crs)
        acquired = (src.tags().get("ACQUISITION_DATE") or
                    src.tags().get("TIFFTAG_DATETIME"))
        valid_pixels = classified_pixels = 0
        transitions = 0
        sum_confidence = 0.
        with ScratchPool(memory_mb*1024*1024) as pool, \
                _scratch(plan, "geofathom-semantic-") as (temp, scratch_quota):
            output = temp / "classes.tif"
            with rasterio.open(output, "w", driver="GTiff",
                               width=src.width, height=src.height,
                               count=1, dtype="uint8", crs=src.crs,
                               transform=src.transform, nodata=0,
                               tiled=True, blockxsize=128, blockysize=128,
                               compress="deflate") as target:
                iterator = iter(context_tiles(src.width,src.height,plan.tile_size,halo))
                number=0
                while True:
                    group=list(islice(iterator,batch_size))
                    if not group:
                        break
                    validity=[]
                    if progress is not None:
                        progress(number/tile_count)
                    shape=(len(group),len(config["bands"]),plan.tile_size,plan.tile_size)
                    with pool.floats(shape) as tensor:
                        for n,tile in enumerate(group):
                            raw,valid=_tile_bands(src,config["bands"],tile.read)
                            rows,cols=int(tile.read.height),int(tile.read.width)
                            normalized=(np.nan_to_num(raw,nan=0.,posinf=0.,neginf=0.) /
                                        config["input_scale"]-mean)/std
                            y,x=tile.input_row,tile.input_col
                            tensor[n,:,y:y+rows,x:x+cols]=normalized
                            core_valid=np.zeros((plan.tile_size,plan.tile_size),bool)
                            core_valid[y:y+rows,x:x+cols]=valid
                            validity.append(core_valid[tile.crop].copy())
                        if len(group)==1:
                            labels,confidence=_predict_tile(tensor,config,device)
                            labels,confidence=labels[None],confidence[None]
                        else:
                            labels,confidence=_predict_batch(tensor,config,device)
                    for n,tile in enumerate(group):
                        number+=1
                        valid=validity[n]
                        conf=confidence[n][tile.crop]
                        accepted=valid & np.isfinite(conf) & (conf>=minimum_confidence)
                        current=np.where(accepted,labels[n][tile.crop],0).astype(np.uint8)
                        transitions+=_transitions(current)
                        if transitions>MAX_BOUNDARY_TRANSITIONS:
                            raise RasterError("Raster mask is too fragmented for safe vectorization.")
                        target.write(current,1,window=tile.core)
                        if number%16==0:
                            _check_scratch(output,scratch_quota)
                        foreground=current!=0
                        valid_pixels+=int(valid.sum())
                        classified_pixels+=int(foreground.sum())
                        sum_confidence+=float(conf[foreground].sum())
            _check_scratch(output, scratch_quota)
            if progress is not None:
                progress(.93)
            features, truncated = _disk_features(
                output, {i: name for i, name in enumerate(config["classes"])
                         if i != 0}, progress=progress)
        if progress is not None:
            progress(1.)
    for feature in features:
        feature["properties"].update({
            "image_id": image_id, "model_id": model_id,
            "provider": "onnxruntime", "min_confidence": minimum_confidence})
    return {"type": "FeatureCollection", "features": features,
            "analysis": "semantic_segmentation",
            "engine": "rasterio-stream+onnxruntime-" + device,
            "provider": "onnxruntime", "model_id": model_id,
            "source_images": [image_id], "acquired_at": acquired,
            "source_crs": crs, "geometry_crs": "EPSG:4326",
            "pixel_grid": [plan.width, plan.height],
            "valid_pixels": valid_pixels, "classified_pixels": classified_pixels,
            "mean_model_confidence": sum_confidence / classified_pixels
                                     if classified_pixels else None,
            "confidence_calibrated": False,
            "tile_count": tile_count, "tile_size": plan.tile_size,
            "context_halo": halo, "batch_size": batch_size,
            "memory_budget_mb": memory_mb, "truncated": truncated,
            "warning": "Model tiles may have edge artifacts and confidence "
                       "is not calibrated. Inspect polygon boundaries and "
                       "underlying imagery before acceptance."}
