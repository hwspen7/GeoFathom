"""Native spectral raster primitives, with deterministic NumPy fallbacks.

GDAL handles CRS, nodata and band alignment outside this module. Native kernels
only process contiguous float32 values and uint8 validity masks, never
untrusted image addresses or pixel counts.
"""
import ctypes
import math
import os
from .cuda import handle as cuda_handle

import numpy as np

from .topology import _native
from .runtime import handle as runtime_handle

_MAX_PIXELS = 16 * 1024 * 1024


def _arrays(first, second, valid):
    a = np.asarray(first, dtype=np.float32)
    b = np.asarray(second, dtype=np.float32)
    mask = np.asarray(valid, dtype=np.uint8)
    if (a.ndim != 2 or a.shape != b.shape or a.shape != mask.shape
            or not 0 < a.size <= _MAX_PIXELS):
        raise ValueError("Spectral inputs require equally sized nonempty 2D raster arrays.")
    return (np.ascontiguousarray(a), np.ascontiguousarray(b),
            np.ascontiguousarray(mask))


def _pointer(a, scalar):
    return a.ctypes.data_as(ctypes.POINTER(scalar))


def normalized_difference(first, second, valid):
    """Return bounded normalized difference, validity and actual computation engine."""
    a, b, mask = _arrays(first, second, valid)
    result = np.zeros(a.shape, dtype=np.float32)
    output_valid = np.zeros(a.shape, dtype=np.uint8)
    lib = _native()
    device = os.getenv("GEOFATHOM_SPECTRAL_DEVICE","cpu").lower()
    if device not in ("cpu","cuda"):
        raise ValueError("Spectral device must be cpu or cuda.")
    if device=="cuda" and lib is None:
        raise RuntimeError("Native CUDA library is unavailable.")
    if lib is not None and hasattr(lib, "gf_spectral_normalized_difference"):
        fn = lib.gf_spectral_normalized_difference
        fn.argtypes = [
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8),
        ]
        fn.restype = ctypes.c_int
        owner = cuda_handle(lib,a.size) if device=='cuda' else runtime_handle(lib)
        args = ()
        if owner is not None:
            argtypes = fn.argtypes
            fn = lib.gf_cuda_runtime_index if device=='cuda' else lib.gf_cpu_runtime_index
            fn.argtypes = [ctypes.c_void_p] + argtypes
            fn.restype = ctypes.c_int
            args = (owner,)
        accepted = fn(*args, _pointer(a, ctypes.c_float), _pointer(b, ctypes.c_float),
                      _pointer(mask, ctypes.c_uint8), a.size,
                      _pointer(result, ctypes.c_float),
                      _pointer(output_valid, ctypes.c_uint8))
        if accepted < 0:
            raise ValueError("Native spectral index computation rejected the input.")
        return result, output_valid.astype(bool), "cuda-spectral" if device=="cuda" else "cpp-spectral"

    finite = (mask != 0) & np.isfinite(a) & np.isfinite(b)
    # Float64 intermediates match the native double-precision accumulation.
    x = a.astype(np.float64)
    y = b.astype(np.float64)
    denominator = x + y
    usable = finite & np.isfinite(denominator) & (np.abs(denominator) > 1e-9)
    np.divide(x - y, denominator, out=result, where=usable, casting="unsafe")
    np.clip(result, -1, 1, out=result)
    return result, usable, "numpy-spectral"


def classify_change(before, before_valid, after, after_valid, threshold):
    """Return 0=unchanged/invalid, 1=gain, 2=loss and the computation engine."""
    if (not isinstance(threshold, (float, int)) or isinstance(threshold, bool)
            or not math.isfinite(threshold) or not 0 < threshold < 1):
        raise ValueError("Change threshold must be finite and strictly between zero and one.")
    old, new, valid = _arrays(before, after, before_valid)
    new_valid = np.asarray(after_valid, dtype=np.uint8)
    if new_valid.shape != old.shape:
        raise ValueError("Change masks must share the same pixel grid.")
    new_valid = np.ascontiguousarray(new_valid)
    labels = np.zeros(old.shape, dtype=np.uint8)
    lib = _native()
    device = os.getenv("GEOFATHOM_SPECTRAL_DEVICE","cpu").lower()
    if device not in ("cpu","cuda"):
        raise ValueError("Spectral device must be cpu or cuda.")
    if device=="cuda" and lib is None:
        raise RuntimeError("Native CUDA library is unavailable.")
    if lib is not None and hasattr(lib, "gf_spectral_change"):
        fn = lib.gf_spectral_change
        fn.argtypes = [
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8),
            ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t, ctypes.c_float, ctypes.POINTER(ctypes.c_uint8),
        ]
        fn.restype = ctypes.c_int
        owner = cuda_handle(lib,old.size) if device=='cuda' else runtime_handle(lib)
        args = ()
        if owner is not None:
            argtypes = fn.argtypes
            fn = lib.gf_cuda_runtime_change if device=='cuda' else lib.gf_cpu_runtime_change
            fn.argtypes = [ctypes.c_void_p] + argtypes
            fn.restype = ctypes.c_int
            args = (owner,)
        changed = fn(*args, _pointer(old, ctypes.c_float),
                     _pointer(valid, ctypes.c_uint8),
                     _pointer(new, ctypes.c_float),
                     _pointer(new_valid, ctypes.c_uint8),
                     old.size, threshold, _pointer(labels, ctypes.c_uint8))
        if changed < 0:
            raise ValueError("Native change classification rejected the input.")
        return labels, "cuda-spectral" if device=="cuda" else "cpp-spectral"

    usable = ((valid != 0) & (new_valid != 0) &
              np.isfinite(old) & np.isfinite(new))
    delta = new.astype(np.float64) - old.astype(np.float64)
    labels[usable & (delta >= np.float32(threshold))] = 1
    labels[usable & (delta <= -np.float32(threshold))] = 2
    return labels, "numpy-spectral"
