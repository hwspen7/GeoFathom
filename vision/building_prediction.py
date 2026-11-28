"""Shared native-pixel building fields for scientific model comparison.

Pixel-only benchmark imagery stays pixel-only. No CRS or ground footprint area
is invented when a dataset publisher has removed geographic metadata.
"""
import math
import os

import numpy as np
import rasterio

from imagery.raster import RasterError
from .semantic import _manifest, fuse_building_heads
from .tiled import _tile_bands
from .tiles import context_tiles


def prepare_building_tile(source, tile, config):
    """Shared source read, RGB normalization and output validity."""
    raw, valid = _tile_bands(source, config["bands"], tile.read)
    if np.any(raw[:, valid] < 0) or np.any(raw[:, valid] > config["input_scale"]):
        raise RasterError("Source pixel range exceeds the building model input scale.")
    mean = np.asarray(config["mean"], np.float32)[:, None, None]
    std = np.asarray(config["std"], np.float32)[:, None, None]
    normalized = (np.where(valid[None], raw, 0.)/config["input_scale"]-mean)/std
    y, x = tile.input_row, tile.input_col
    h, w = valid.shape
    size = config["tile_size"]
    pad = ((y, size-h-y), (x, size-w-x))
    tensor = np.pad(normalized, ((0, 0), *pad), mode="edge")[None]
    support = np.pad(valid, pad, mode="constant", constant_values=False)
    return np.ascontiguousarray(tensor, dtype=np.float32), support[tile.crop].copy()


def predict_image(path, model_id, *, device=None, memory_mb=256, progress=None, augmentation="none"):
    if augmentation not in ("none", "flips", "multiscale", "hybrid"):
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
        if augmentation == "hybrid":
            fields["view_disagreement"] = np.zeros(source.shape, np.float32)
        for name in ("boundary", "distance"):
            if config.get(name+"_channel") is not None:
                fields[name] = np.zeros(source.shape, np.float32)
        valid_image = np.zeros(source.shape, bool)
        size, halo = config["tile_size"], config["halo"]
        count = math.ceil(source.height/(size-2*halo)) * math.ceil(source.width/(size-2*halo))
        for index, tile in enumerate(context_tiles(source.width, source.height, size, halo)):
            if progress is not None:
                progress(index/count)
            tensor, core_valid = prepare_building_tile(source, tile, config)
            heads = fuse_building_heads(tensor, config, device, augmentation=augmentation,
                        check=(lambda: progress(index/count)) if progress is not None else None)
            rows = slice(int(tile.core.row_off), int(tile.core.row_off+tile.core.height))
            cols = slice(int(tile.core.col_off), int(tile.core.col_off+tile.core.width))
            valid_image[rows, cols] = core_valid
            for name, target in fields.items():
                target[rows, cols] = np.where(core_valid, heads[name][tile.crop], -1. if name == "probability" else 0.)
        fields["valid"] = valid_image
    return fields
