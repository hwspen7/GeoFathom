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
from pathlib import Path

import numpy as np
import rasterio

from imagery.raster import RasterError
from .geoai import _window, _vector_features
from .runtime import (pool_for, tensor_budget_mb, gpu_arena_budget_mb,
                      cpu_threads)

_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "vision-models"


def model_directory():
    from storage.snapshots import model_override
    return model_override() or Path(os.getenv("GEOFATHOM_VISION_MODELS_DIR") or _DEFAULT_ROOT).expanduser().resolve()


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
    halo = info.get("halo", 0)
    max_batch = info.get("max_batch", 1)
    # Binary/multi-task heads must never be decoded as competing land-cover classes.
    output_type = info.get("output_type", "logits")
    output_channels = info.get("output_channels", len(classes) if isinstance(classes, list) else 0)
    output_channel = info.get("output_channel", 0)
    task = info.get("task", "semantic_segmentation")
    if (output_type not in ("logits", "binary_logits", "binary_probability")
            or type(output_channels) is not int or not 1 <= output_channels <= 32
            or type(output_channel) is not int or not 0 <= output_channel < output_channels
            or task not in ("semantic_segmentation", "building_extraction")):
        raise RasterError("Invalid model task or output head contract.")
    mean = info.get("mean", [0] * len(bands) if isinstance(bands,list) else [])
    std = info.get("std", [1] * len(bands) if isinstance(bands,list) else [])
    if (not isinstance(classes, list) or not 2 <= len(classes) <= 32 or
        any(not isinstance(x, str) or not x or len(x) > 64 for x in classes) or
        not isinstance(bands, list) or not 1 <= len(bands) <= 20 or
        any(type(b) is not int or not 1 <= b <= 20 for b in bands) or
        len(set(bands)) != len(bands) or type(size) is not int
        or size not in (128, 256, 512)):
        raise RasterError("Model requires class names, three bands and a supported tile size.")
    if type(max_batch) is not int or not 1 <= max_batch <= 16:
        raise RasterError("Model max_batch must be an integer from 1 to 16.")
    if type(halo) is not int or not 0 <= halo <= size // 4:
        raise RasterError("Model halo must be 0 to one quarter of tile size.")
    if (not isinstance(scale, (float, int)) or not math.isfinite(scale)
        or not 0 < scale <= 65535):
        raise RasterError("Model input scale must be a positive finite number.")
    for values in (mean, std):
        if (not isinstance(values, list) or len(values) != len(bands) or
            any(not isinstance(x, (float, int)) or isinstance(x, bool)
                or not math.isfinite(x) for x in values)):
            raise RasterError("Model normalization must match selected input bands.")
    if any(x <= 0 for x in std):
        raise RasterError("Model normalization standard deviations must be positive.")
    if output_type != "logits" and len(classes) != 2:
        raise RasterError("Binary model heads require exactly two class names.")
    if output_type == "logits" and output_channels != len(classes):
        raise RasterError("Logit output channels must match class names.")
    return {
        "id": identifier, "classes": classes, "bands": bands,
        "tile_size": size, "halo": halo, "max_batch": max_batch, "input_scale": float(scale),
        "mean": [float(x) for x in mean], "std": [float(x) for x in std],
        "description": str(info.get("description", ""))[:180],
        "task": task, "output_type": output_type,
        "output_channels": output_channels, "output_channel": output_channel,
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


def _session(path, modified_ns, device):
    """Construct one session; the external pool owns reuse and lifetime."""
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise RuntimeError("Install the optional onnxruntime package to run this model.") from error
    # Local scientific inference does not need runtime usage telemetry.
    disable_telemetry = getattr(ort, "disable_telemetry_events", None)
    if disable_telemetry is not None:
        disable_telemetry()
    options = ort.SessionOptions()
    options.intra_op_num_threads = cpu_threads()
    options.inter_op_num_threads = 1
    providers = ["CPUExecutionProvider"]
    if device == "cuda":
        from core.cuda_environment import prepare_onnx_cuda
        prepare_onnx_cuda(ort)
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("ONNX CUDA provider is unavailable.")
        # An arena limit is advisory: weights, kernels and external drivers
        # can allocate memory outside the CUDA execution-provider arena.
        strict=os.getenv("GEOFATHOM_VISION_STRICT_CUDA","0")=="1"
        device_id=int(os.getenv("GEOFATHOM_CUDA_DEVICE_ID","0"))
        if device_id<0:
            raise ValueError("ONNX CUDA device ID must be nonnegative.")
        providers = [("CUDAExecutionProvider", {
            "gpu_mem_limit": str(gpu_arena_budget_mb() * 1024 * 1024),
            "device_id": str(device_id),
        })]
        if strict:
            # Strict mode rejects graphs with CPU-only node placement as well
            # as whole-provider retries; it is opt-in for supported models.
            options.add_session_config_entry("session.disable_cpu_ep_fallback","1")
        else:
            providers.append("CPUExecutionProvider")
    session = ort.InferenceSession(path, sess_options=options,
                                   providers=providers)
    if device == "cuda":
        if session.get_providers()[0] != "CUDAExecutionProvider":
            raise RuntimeError("ONNX CUDA session fell back to CPU unexpectedly.")
        # Disable provider-wide retry on CPU; normal ORT per-node placement is
        # unchanged for models containing CPU-only shape/control operations.
        session.disable_fallback()
    return session


def _predict_batch(tensor, config, device):
    path = config["model_path"]
    size = config["tile_size"]
    classes = len(config["classes"])
    # Budget model input/output tensors before allocating native sessions.
    # It does not bound all ONNX Runtime activations or GPU driver memory.
    channels = len(config.get("bands", [1, 2, 3]))
    batch = tensor.shape[0] if tensor.ndim == 4 else 0
    # Count working logits, softmax intermediates, masks and input.
    expected_bytes = batch * size * size * (channels + 4 * max(classes, config.get("output_channels", classes)) + 12) * 4
    if (not 1 <= batch <= config.get("max_batch", 1)
            or tensor.shape != (batch, channels, size, size) or tensor.dtype != np.float32
            or expected_bytes > tensor_budget_mb() * 1024 * 1024):
        raise RasterError("Model tile exceeds the configured tensor memory budget.")
    state = path.stat()
    # Include the runtime arena policy in the session identity, and account
    # the model bytes plus a declared arena/overhead reservation. Providers
    # may allocate outside an arena; this is admission, not a driver quota.
    overhead=(gpu_arena_budget_mb() if device=="cuda" else 128)*1024**2
    device_id=int(os.getenv("GEOFATHOM_CUDA_DEVICE_ID","0")) if device=="cuda" else 0
    # The native decoder handles competing logits; binary auxiliary heads use host decoding.
    gpu_decode=(device=="cuda" and config.get("output_type", "logits")=="logits"
                and os.getenv("GEOFATHOM_VISION_DEVICE_POSTPROCESS","0")=="1")
    strict=device=="cuda" and os.getenv("GEOFATHOM_VISION_STRICT_CUDA","0")=="1"
    key=(str(path.resolve()),state.st_mtime_ns,state.st_size,device,overhead,device_id,strict)
    with pool_for(device).lease(key,lambda:_session(str(path),state.st_mtime_ns,device),
            reserved_bytes=state.st_size+overhead,working_bytes=int(expected_bytes)) as session:
        inputs = session.get_inputs()
        if len(inputs) != 1:
            raise RasterError("Semantic model must accept exactly one image tensor.")
        if device=="cuda" and (gpu_decode or os.getenv("GEOFATHOM_VISION_IO_BINDING","0")=="1"):
            # ONNX Runtime manages CUDA output allocation. Source pixels still
            # originate on CPU and classifications return to CPU for GIS
            # polygonization: this path is NOT a GPU zero-copy pipeline.
            names=session.get_outputs()
            if not names:
                raise RasterError("Semantic model has no declared output.")
            binding=session.io_binding()
            binding.bind_cpu_input(inputs[0].name,tensor)
            if gpu_decode or device_id:
                binding.bind_output(names[0].name,"cuda",device_id)
            else:
                binding.bind_output(names[0].name,"cuda")
            session.run_with_iobinding(binding)
            if gpu_decode:
                binding.synchronize_outputs()
                device_values=binding.get_outputs()
                if not device_values:
                    raise RasterError("Semantic model returned no CUDA output.")
                from .device_postprocess import decode_cuda_logits
                return decode_cuda_logits(device_values[0],batch,classes,size,device_id)
            outputs=binding.copy_outputs_to_cpu()
        else:
            outputs = session.run(None, {inputs[0].name: tensor})
        if not outputs:
            raise RasterError("Semantic model returned no output.")
        raw = outputs[0]
    if not isinstance(raw, np.ndarray) or not np.isfinite(raw).all():
        raise RasterError("Model output contains nonfinite predictions.")
    if config.get("output_type", "logits") != "logits":
        expected = (batch, config["output_channels"], size, size)
        if raw.shape != expected or not np.issubdtype(raw.dtype, np.floating):
            raise RasterError("Binary model output does not match its declared head shape.")
        probability = raw[:, config["output_channel"]].astype(np.float32)
        if config["output_type"] == "binary_logits":
            # Stable sigmoid avoids overflow for confidently negative logits.
            probability = np.exp(-np.logaddexp(0., -probability))
        elif np.any((probability < 0) | (probability > 1)):
            raise RasterError("Binary model probabilities must be between zero and one.")
        predicted = (probability >= .5).astype(np.uint8)
        confidence = np.maximum(probability, 1 - probability).astype(np.float32)
    elif raw.ndim == 4 and raw.shape == (batch, classes, size, size):
        logits = raw.astype(np.float32)
        logits -= logits.max(axis=1, keepdims=True)
        np.exp(logits, out=logits)
        logits /= np.maximum(logits.sum(axis=1, keepdims=True), 1e-12)
        predicted = logits.argmax(axis=1).astype(np.uint8)
        confidence = logits.max(axis=1).astype(np.float32)
    elif raw.ndim == 3 and raw.shape == (batch, size, size):
        if (not np.issubdtype(raw.dtype, np.integer)
                or np.any(raw < 0) or np.any(raw >= classes)):
            raise RasterError("Integer model output contains invalid class IDs.")
        predicted = raw.astype(np.uint8)
        # Hard class labels are not calibrated probability estimates.
        confidence = np.ones((batch, size, size), dtype=np.float32)
    else:
        raise RasterError("Model output must be [N,C,H,W] logits or [N,H,W] class IDs.")
    if np.any(predicted >= classes):
        raise RasterError("Model predicted a class index outside its manifest.")
    return predicted, confidence


def _predict_tile(tensor, config, device):
    predicted, confidence = _predict_batch(tensor, config, device)
    if len(predicted) != 1:
        raise RasterError("Single tile prediction requires batch size one.")
    return predicted[0], confidence[0]


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
            padded = np.zeros((1, len(config["bands"]), size, size), dtype=np.float32)
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
        "confidence_calibrated": False,
        "truncated": truncated,
        "warning": "Model predictions depend on training domain, selected bands, "
                   "normalization and georeferencing. Polygon boundaries are "
                   "image-derived estimates and require manual verification."}
