"""Replaceable, local ONNX semantic segmentation for georeferenced imagery.

Models are provisioned by an administrator on the server. Browser requests
select a validated model identifier, never a filesystem path or remote URL.
No weights, training data or ONNX runtime are downloaded automatically.
"""
import importlib.util
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio

from imagery.raster import RasterError
from .geoai import _window, _vector_features

_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "vision-models"


def model_directory():
    return Path(os.getenv("GEOFATHOM_VISION_MODELS_DIR") or _DEFAULT_ROOT).expanduser().resolve()


def _manifest(identifier):
    if not isinstance(identifier, str) or not _MODEL_NAME.fullmatch(identifier):
        raise RasterError("Invalid vision model identifier.")
    root = model_directory()
    weights = root / (identifier + ".onnx")
    manifest = root / (identifier + ".json")
    # Refuse symlinks and aliases that leave the explicitly configured directory.
    if (weights.is_symlink() or manifest.is_symlink() or
        weights.resolve().parent != root or manifest.resolve().parent != root):
        raise RasterError("Vision model files must stay inside the configured model directory.")
    if not weights.is_file() or not manifest.is_file():
        raise RasterError("Configured ONNX model and JSON manifest are both required.")
    if manifest.stat().st_size > 32_768:
        raise RasterError("Vision model manifest is too large.")
    try:
        info = json.loads(manifest.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise RasterError("Vision model manifest is invalid JSON.") from error
    if not isinstance(info, dict):
        raise RasterError("Vision model manifest must be an object.")
    classes = info.get("classes")
    bands = info.get("bands", [1, 2, 3])
    size = info.get("tile_size", 256)
    scale = info.get("input_scale", 255.0)
    mean = info.get("mean", [0, 0, 0])
    std = info.get("std", [1, 1, 1])
    if (not isinstance(classes, list) or not 2 <= len(classes) <= 32 or
        any(not isinstance(x, str) or not x or len(x) > 64 for x in classes) or
        not isinstance(bands, list) or len(bands) != 3 or
        any(type(b) is not int or not 1 <= b <= 20 for b in bands) or
        len(set(bands)) != 3 or type(size) is not int or size not in (128, 256, 512)):
        raise RasterError("Model requires class names, three bands and a supported tile size.")
    if (not isinstance(scale, (float, int)) or not math.isfinite(scale)
        or not 0 < scale <= 65535):
        raise RasterError("Model input scale must be a positive finite number.")
    for values in (mean, std):
        if (not isinstance(values, list) or len(values) != 3 or
            any(not isinstance(x, (float, int)) or isinstance(x, bool)
                or not math.isfinite(x) for x in values)):
            raise RasterError("Model normalization requires three finite values.")
    if any(x <= 0 for x in std):
        raise RasterError("Model normalization standard deviations must be positive.")
    return {
        "id": identifier, "classes": classes, "bands": bands,
        "tile_size": size, "input_scale": float(scale),
        "mean": [float(x) for x in mean], "std": [float(x) for x in std],
        "description": str(info.get("description", ""))[:180],
        "runtime": "onnxruntime", "model_path": weights,
    }


def models():
    root = model_directory()
    available = importlib.util.find_spec("onnxruntime") is not None
    entries = []
    if root.is_dir():
        for file in sorted(root.glob("*.onnx"))[:30]:
            try:
                meta = _manifest(file.stem)
                entries.append({k: v for k, v in meta.items() if k != "model_path"})
            except RasterError:
                continue
    return {"models": entries, "runtime_available": available,
            "device": os.getenv("GEOFATHOM_VISION_DEVICE", "cpu"),
            "note": "Model files and manifests are installed locally by the operator."}


@lru_cache(maxsize=2)
def _session(path, modified_ns, device):
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise RuntimeError("Install the optional onnxruntime package to run this model.") from error
    providers = ["CPUExecutionProvider"]
    if device == "cuda":
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("ONNX CUDA provider is unavailable.")
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ort.InferenceSession(path, providers=providers)


def _predict_tile(tensor, config, device):
    path = config["model_path"]
    session = _session(str(path), path.stat().st_mtime_ns, device)
    inputs = session.get_inputs()
    if len(inputs) != 1:
        raise RasterError("Semantic model must accept exactly one image tensor.")
    raw = session.run(None, {inputs[0].name: tensor})[0]
    size = config["tile_size"]
    classes = len(config["classes"])
    if raw.ndim == 4 and raw.shape == (1, classes, size, size):
        logits = raw[0].astype(np.float32)
        logits -= logits.max(axis=0)
        exponential = np.exp(logits)
        probabilities = exponential / np.maximum(exponential.sum(axis=0), 1e-12)
        predicted = probabilities.argmax(axis=0).astype(np.uint8)
        confidence = probabilities.max(axis=0).astype(np.float32)
    elif raw.ndim == 3 and raw.shape == (1, size, size):
        predicted = raw[0].astype(np.uint8)
        confidence = np.ones((size, size), dtype=np.float32)
    else:
        raise RasterError("Model output must be [1,C,H,W] logits or [1,H,W] class IDs.")
    if np.any(predicted >= classes):
        raise RasterError("Model predicted a class index outside its manifest.")
    return predicted, confidence


def semantic_segmentation(path: Path, image_id: str, model_id: str,
                          minimum_confidence: float = .55,
                          max_side: int = 512):
    if not math.isfinite(minimum_confidence) or not 0 <= minimum_confidence <= 1:
        raise RasterError("Confidence threshold must be between zero and one.")
    config = _manifest(model_id)
    device = os.getenv("GEOFATHOM_VISION_DEVICE", "cpu").lower()
    if device not in ("cpu", "cuda"):
        raise RasterError("Vision device must be cpu or cuda.")
    with rasterio.open(path) as src:
        values, valid, affine = _window(src, config["bands"], max_side)
        crs = str(src.crs)
        acquisition = src.tags().get("ACQUISITION_DATE") or src.tags().get("TIFFTAG_DATETIME")
    width, height = values.shape[2], values.shape[1]
    size = config["tile_size"]
    if math.ceil(height / size) * math.ceil(width / size) > 36:
        raise RasterError("Semantic inference exceeds the 36-tile limit.")
    labels = np.zeros((height, width), dtype=np.uint8)
    confidence = np.zeros((height, width), dtype=np.float32)
    mean = np.asarray(config["mean"], dtype=np.float32)[:, None, None]
    std = np.asarray(config["std"], dtype=np.float32)[:, None, None]
    for row in range(0, height, size):
        for col in range(0, width, size):
            bottom, right = min(row + size, height), min(col + size, width)
            tile = values[:, row:bottom, col:right]
            # Zero padding is applied after normalization so out-of-image
            # pixels are neutral in model input space and never vectorized.
            normalized = (np.nan_to_num(tile, nan=0.0) /
                          config["input_scale"] - mean) / std
            padded = np.zeros((1, 3, size, size), dtype=np.float32)
            padded[0, :, :bottom-row, :right-col] = normalized
            predicted, scores = _predict_tile(padded, config, device)
            accepted = scores[:bottom-row, :right-col] >= minimum_confidence
            labels[row:bottom, col:right] = np.where(
                accepted, predicted[:bottom-row, :right-col], 0)
            confidence[row:bottom, col:right] = scores[:bottom-row, :right-col]
    labels[~valid] = 0
    features, truncated = _vector_features(
        labels, affine, crs,
        {index: name for index, name in enumerate(config["classes"]) if index != 0},
    )
    for feature in features:
        feature["properties"].update({"image_id": image_id, "model_id": model_id,
            "provider": "onnxruntime", "min_confidence": minimum_confidence})
    foreground = labels != 0
    return {"type": "FeatureCollection", "features": features,
        "analysis": "semantic_segmentation", "engine": "onnxruntime-tiled-nchw",
        "provider": "onnxruntime", "model_id": model_id,
        "source_images": [image_id], "acquired_at": acquisition,
        "source_crs": crs, "geometry_crs": "EPSG:4326",
        "pixel_grid": [width, height], "valid_pixels": int(valid.sum()),
        "classified_pixels": int(foreground.sum()),
        "mean_model_confidence": float(confidence[foreground].mean())
                                 if foreground.any() else None,
        "truncated": truncated,
        "warning": "Model predictions depend on training domain, selected bands, "
                   "normalization and georeferencing. Polygon boundaries are "
                   "image-derived estimates and require manual verification."}
