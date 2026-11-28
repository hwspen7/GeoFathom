"""Shared native-pixel building fields for scientific model comparison.

Pixel-only benchmark imagery stays pixel-only. No CRS or ground footprint area
is invented when a dataset publisher has removed geographic metadata.
"""
import math
import os

import numpy as np
import rasterio

from imagery.raster import RasterError
from .semantic import _manifest, predict_building_heads, fuse_building_heads
from .tiles import context_tiles


def predict_image(path, model_id, *, device=None, memory_mb=256, progress=None, augmentation="none"):
    if augmentation not in ("none", "flips", "multiscale"):
        raise RasterError("Unsupported building inference augmentation.")
    config = _manifest(model_id)
    if config["task"] != "building_extraction" or config["output_type"] == "logits":
        raise RasterError("Choose a building model with a declared binary head.")
    device = device or os.getenv("GEOFATHOM_VISION_DEVICE", "cpu").lower()
    if device not in ("cpu", "cuda"):
        raise RasterError("Unsupported building inference device.")
    with rasterio.open(path) as source:
        if (max(source.shape) > 8192 or min(source.shape) < 1 or
                max(config["bands"]) > source.count or
                source.width * source.height * 48 > memory_mb * 1024**2):
            raise RasterError("Benchmark image exceeds the declared memory or band budget.")
        fields = {"probability": np.full(source.shape, -1., np.float32)}
        for name in ("boundary", "distance"):
            if config.get(name+"_channel") is not None:
                fields[name] = np.zeros(source.shape, np.float32)
        valid_image = np.zeros(source.shape, bool)
        size, halo = config["tile_size"], config["halo"]
        mean = np.asarray(config["mean"], np.float32)[:, None, None]
        std = np.asarray(config["std"], np.float32)[:, None, None]
        count = math.ceil(source.height/(size-2*halo)) * math.ceil(source.width/(size-2*halo))
        for index, tile in enumerate(context_tiles(source.width, source.height, size, halo)):
            if progress is not None:
                progress(index/count)
            raw = source.read(config["bands"], window=tile.read, masked=True).astype(np.float32)
            valid = ~np.any(np.ma.getmaskarray(raw), axis=0) & np.isfinite(raw.data).all(axis=0)
            if np.any(raw.data[:, valid] < 0) or np.any(raw.data[:, valid] > config["input_scale"]):
                raise RasterError("Benchmark RGB encoding differs from the model input scale.")
            normalized = (np.nan_to_num(raw.filled(0.), nan=0.) / config["input_scale"]-mean)/std
            y, x = tile.input_row, tile.input_col
            h, w = valid.shape
            tensor = np.pad(normalized, ((0, 0), (y, size-h-y), (x, size-w-x)), mode="edge")[None]
            heads = (predict_building_heads(tensor.astype(np.float32), config, device)
                     if augmentation == "none" else fuse_building_heads(tensor.astype(np.float32), config, device, augmentation=augmentation,
                        check=(lambda: progress(index/count)) if progress is not None else None))
            rows = slice(int(tile.core.row_off), int(tile.core.row_off+tile.core.height))
            cols = slice(int(tile.core.col_off), int(tile.core.col_off+tile.core.width))
            core_valid = valid[halo-y:halo-y+int(tile.core.height), halo-x:halo-x+int(tile.core.width)]
            valid_image[rows, cols] = core_valid
            for name, target in fields.items():
                target[rows, cols] = np.where(core_valid, heads[name][tile.crop], -1. if name == "probability" else 0.)
        fields["valid"] = valid_image
    return fields
