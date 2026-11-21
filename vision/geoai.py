"""Bounded, georeferenced spectral analysis and multi-date change detection.

These are deterministic remote-sensing operators, NOT semantic AI classifiers.
Never assume a GeoTIFF's band order or date. Users specify the band mapping.
All vector outputs are WGS84 estimates with explicit provenance.
"""
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping

from geometry.measure import measure_geometry, GeometryError
from imagery.raster import RasterError, _check

MAX_SIDE = 768
MAX_FEATURES = 100


def _read(src, bands, width, height):
    if not all(isinstance(b, int) and not isinstance(b, bool)
               and 1 <= b <= src.count for b in bands):
        raise RasterError("Selected spectral bands are unavailable in the GeoTIFF.")
    data = src.read(list(bands), out_shape=(len(bands), height, width),
                    resampling=Resampling.average, masked=True)
    invalid = np.any(np.ma.getmaskarray(data), axis=0)
    values = np.ma.filled(data.astype(np.float32), np.nan)
    invalid |= ~np.all(np.isfinite(values), axis=0)
    return values, ~invalid


def _window(src, bands, max_side):
    _check(src)
    if not isinstance(max_side, int) or not 64 <= max_side <= MAX_SIDE:
        raise RasterError("Analysis size must be between 64 and 768 pixels.")
    ratio = min(1.0, max_side / max(src.width, src.height))
    width = max(1, int(round(src.width * ratio)))
    height = max(1, int(round(src.height * ratio)))
    affine = src.transform * Affine.scale(src.width / width, src.height / height)
    values, valid = _read(src, bands, width, height)
    return values, valid, affine


def _ratio(first, second, valid):
    denominator = first + second
    usable = valid & np.isfinite(denominator) & (np.abs(denominator) > 1e-9)
    result = np.zeros(first.shape, dtype=np.float32)
    np.divide(first - second, denominator, out=result, where=usable)
    return np.clip(result, -1, 1), usable


def _vector_features(labels, affine, crs, classes, max_features=MAX_FEATURES,
                     minimum_pixels=9):
    """Vectorize connected pixel regions without fabricating subpixel precision."""
    if not 1 <= max_features <= MAX_FEATURES or not 1 <= minimum_pixels <= 10000:
        raise RasterError("Invalid vector output limits.")
    pixel_area = abs(affine.a * affine.e - affine.b * affine.d)
    if pixel_area <= 0:
        raise RasterError("Non-invertible raster transform.")
    candidates = []
    scanned = 0
    active = labels != 0
    if active.any():
        for geom, value in shapes(labels.astype(np.uint8), mask=active,
                                  transform=affine, connectivity=8):
            scanned += 1
            if scanned > 20000:
                break
            klass = int(value)
            if klass not in classes:
                continue
            polygon = shape(geom)
            pixels = int(round(polygon.area / pixel_area))
            if pixels < minimum_pixels:
                continue
            # Simplification tolerance is expressed in source-CRS units.
            scale = min(abs(affine.a) + abs(affine.d),
                        abs(affine.e) + abs(affine.b))
            if pixels > 100:
                polygon = polygon.simplify(scale * .35, preserve_topology=True)
            if polygon.is_empty or not polygon.is_valid:
                continue
            candidates.append((pixels, klass, polygon))
    candidates.sort(key=lambda item: item[0], reverse=True)
    truncated = len(candidates) > max_features or scanned > 20000
    features = []
    for pixels, klass, polygon in candidates[:max_features]:
        geometry = transform_geom(str(crs), "EPSG:4326", mapping(polygon),
                                  antimeridian_cutting=True, precision=8)
        try:
            measured = measure_geometry(geometry)
        except (GeometryError, ValueError) as error:
            raise RasterError("Detected region cannot be measured in WGS84.") from error
        features.append({"type": "Feature", "geometry": geometry, "properties": {
            "class_id": klass, "class_name": classes[klass],
            "pixel_count": pixels, "area_m2": measured["area_m2"],
            "boundary_status": "estimated_from_imagery",
            "quality": "requires_user_review",
        }})
    return features, truncated


def spectral_index(path: Path, image_id: str, index: str,
                   first_band: int, second_band: int,
                   threshold: float = .2, max_side: int = 512):
    if index not in {"ndvi", "ndwi"}:
        raise RasterError("Supported spectral indices are NDVI and NDWI.")
    if first_band == second_band:
        raise RasterError("The spectral bands must be distinct.")
    if not np.isfinite(threshold) or not -1 < threshold < 1:
        raise RasterError("Spectral threshold must be between -1 and 1.")
    with rasterio.open(path) as src:
        values, valid, affine = _window(src, (first_band, second_band), max_side)
        crs = str(src.crs)
        acquired = src.tags().get("ACQUISITION_DATE") or src.tags().get("TIFFTAG_DATETIME")
    score, usable = _ratio(values[0], values[1], valid)
    labels = np.where(usable & (score >= threshold), 1, 0).astype(np.uint8)
    klass = "vegetation_candidate" if index == "ndvi" else "surface_water_candidate"
    features, truncated = _vector_features(labels, affine, crs, {1: klass})
    for feature in features:
        feature["properties"].update({
            "image_id": image_id, "method": index,
            "bands": [first_band, second_band], "threshold": threshold,
        })
    return {"type": "FeatureCollection", "features": features,
            "analysis": index, "engine": "rasterio-numpy-spectral-index",
            "provider": "deterministic", "model_id": None,
            "source_images": [image_id], "acquired_at": acquired,
            "source_crs": crs, "geometry_crs": "EPSG:4326",
            "pixel_grid": [int(score.shape[1]), int(score.shape[0])],
            "valid_pixels": int(usable.sum()), "classified_pixels": int(labels.sum()),
            "min_threshold": threshold, "truncated": truncated,
            "warning": "Spectral thresholding is not AI object recognition. "
                       "Confirm band identities, atmospheric correction, nodata and "
                       "pixel resolution; all regions require manual review."}


def spectral_change(before_path: Path, after_path: Path,
                    before_id: str, after_id: str, first_band: int,
                    second_band: int, threshold: float = .2,
                    max_side: int = 512):
    if before_id == after_id:
        raise RasterError("Select two different dated rasters.")
    if first_band == second_band:
        raise RasterError("The spectral bands must be distinct.")
    if not np.isfinite(threshold) or not 0 < threshold < 1:
        raise RasterError("Change threshold must be between 0 and 1.")
    with rasterio.open(before_path) as before, rasterio.open(after_path) as after:
        old, old_valid, affine = _window(before, (first_band, second_band), max_side)
        _check(after)
        if after.count < max(first_band, second_band):
            raise RasterError("The second image lacks a selected spectral band.")
        height, width = old.shape[1:]
        with WarpedVRT(after, crs=before.crs, transform=affine, width=width,
                       height=height, resampling=Resampling.bilinear) as aligned:
            new, new_valid = _read(aligned, (first_band, second_band), width, height)
        crs = str(before.crs)
        dates = [
            before.tags().get("ACQUISITION_DATE") or before.tags().get("TIFFTAG_DATETIME"),
            after.tags().get("ACQUISITION_DATE") or after.tags().get("TIFFTAG_DATETIME"),
        ]
    old_index, ov = _ratio(old[0], old[1], old_valid)
    new_index, nv = _ratio(new[0], new[1], new_valid)
    both = ov & nv
    if not both.any():
        raise RasterError("The dated rasters have no valid overlapping pixels.")
    delta = new_index - old_index
    labels = np.zeros(delta.shape, dtype=np.uint8)
    labels[both & (delta >= threshold)] = 1
    labels[both & (delta <= -threshold)] = 2
    features, truncated = _vector_features(
        labels, affine, crs, {1: "index_gain", 2: "index_loss"})
    for feature in features:
        feature["properties"].update({
            "before_image_id": before_id, "after_image_id": after_id,
            "method": "normalized_difference_change",
            "bands": [first_band, second_band], "threshold": threshold,
        })
    return {"type": "FeatureCollection", "features": features,
            "analysis": "spectral_change", "engine": "rasterio-warped-vrt-numpy",
            "provider": "deterministic", "model_id": None,
            "source_images": [before_id, after_id], "acquired_at": dates,
            "source_crs": crs, "geometry_crs": "EPSG:4326",
            "pixel_grid": [int(delta.shape[1]), int(delta.shape[0])],
            "valid_pixels": int(both.sum()),
            "gain_pixels": int((labels == 1).sum()),
            "loss_pixels": int((labels == 2).sum()),
            "truncated": truncated,
            "warning": "Spectral change is not proof of construction, destruction or "
                       "land-cover identity. Registration, season, clouds, shadows "
                       "and radiometric differences can cause false changes."}
