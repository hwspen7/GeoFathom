"""Native spectral raster primitives, with deterministic NumPy fallbacks.

GDAL handles CRS, nodata and band alignment outside this module. Native kernels
only process contiguous float32 values and uint8 validity masks, never
untrusted image addresses or pixel counts.
"""
import ctypes
import math
import os
import logging
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


def _requested_device(lib,count):
    mode=os.getenv("GEOFATHOM_SPECTRAL_DEVICE","cpu").lower()
    if mode not in ("cpu","cuda","auto"):
        raise ValueError("Spectral device must be cpu, cuda or auto.")
    if mode=="auto":
        minimum=int(os.getenv("GEOFATHOM_CUDA_MIN_PIXELS","262144"))
        if not 1<=minimum<=_MAX_PIXELS:
            raise ValueError("Invalid automatic CUDA threshold.")
        if lib is not None and count>=minimum and hasattr(lib,"gf_cuda_runtime_create"):
            return "cuda",True
        return "cpu",True
    if mode=="cuda" and lib is None:
        raise RuntimeError("Native CUDA library is unavailable.")
    return mode,False


def _native_kernel(lib,base,cpu,gpu,count,types,args,device,automatic):
    if device=="cuda":
        try:
            owner=cuda_handle(lib,count)
            fn=getattr(lib,gpu)
            fn.argtypes=[ctypes.c_void_p]+types
            fn.restype=ctypes.c_int
            if fn(owner,*args)<0:
                raise RuntimeError("CUDA spectral computation failed.")
            return "cuda-spectral"
        except (RuntimeError,ValueError,MemoryError,AttributeError):
            if not automatic:
                raise
            logging.getLogger(__name__).warning("CUDA spectral unavailable; retrying on CPU.")
    # CPU output fully overwrites any partially written CUDA output.
    owner=runtime_handle(lib)
    fn=getattr(lib,cpu if owner else base)
    fn.argtypes=([ctypes.c_void_p]+types) if owner else types
    fn.restype=ctypes.c_int
    if (fn(owner,*args) if owner else fn(*args))<0:
        raise ValueError("Native spectral computation rejected the input.")
    return "cpp-spectral"


def normalized_difference(first, second, valid):
    """Return bounded normalized difference, validity and actual computation engine."""
    a, b, mask = _arrays(first, second, valid)
    result = np.zeros(a.shape, dtype=np.float32)
    output_valid = np.zeros(a.shape, dtype=np.uint8)
    lib = _native()
    device,automatic=_requested_device(lib,a.size)
    if lib is not None and hasattr(lib,"gf_spectral_normalized_difference"):
        types=[ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_float),
               ctypes.POINTER(ctypes.c_uint8),ctypes.c_size_t,
               ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_uint8)]
        args=(_pointer(a,ctypes.c_float),_pointer(b,ctypes.c_float),
              _pointer(mask,ctypes.c_uint8),a.size,_pointer(result,ctypes.c_float),
              _pointer(output_valid,ctypes.c_uint8))
        engine=_native_kernel(lib,"gf_spectral_normalized_difference","gf_cpu_runtime_index",
            "gf_cuda_runtime_index",a.size,types,args,device,automatic)
        return result,output_valid.astype(bool),engine

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
    device,automatic=_requested_device(lib,old.size)
    if lib is not None and hasattr(lib,"gf_spectral_change"):
        types=[ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_uint8),
               ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_uint8),
               ctypes.c_size_t,ctypes.c_float,ctypes.POINTER(ctypes.c_uint8)]
        args=(_pointer(old,ctypes.c_float),_pointer(valid,ctypes.c_uint8),
              _pointer(new,ctypes.c_float),_pointer(new_valid,ctypes.c_uint8),
              old.size,threshold,_pointer(labels,ctypes.c_uint8))
        engine=_native_kernel(lib,"gf_spectral_change","gf_cpu_runtime_change",
            "gf_cuda_runtime_change",old.size,types,args,device,automatic)
        return labels,engine

    usable = ((valid != 0) & (new_valid != 0) &
              np.isfinite(old) & np.isfinite(new))
    delta = new.astype(np.float64) - old.astype(np.float64)
    labels[usable & (delta >= np.float32(threshold))] = 1
    labels[usable & (delta <= -np.float32(threshold))] = 2
    return labels, "numpy-spectral"

def paired_change(old_bands,old_valid,new_bands,new_valid,threshold):
    """Keep the intermediate normalized indices on GPU when CUDA is selected.

    Host raster input and final GIS labels still cross the device boundary.
    Return final labels, joint valid-pixel mask, actual engine and index engines.
    """
    if (not isinstance(threshold,(int,float)) or isinstance(threshold,bool)
            or not math.isfinite(threshold) or not 0<threshold<1):
        raise ValueError("Invalid spectral change threshold.")
    a,b,av=_arrays(old_bands[0],old_bands[1],old_valid)
    c,d,bv=_arrays(new_bands[0],new_bands[1],new_valid)
    if a.shape!=c.shape:
        raise ValueError("Dated spectral grids must match.")
    lib=_native()
    device,automatic=_requested_device(lib,a.size)
    if device=="cuda":
        try:
            labels=np.zeros(a.shape,np.uint8)
            valid=np.zeros(a.shape,np.uint8)
            owner=cuda_handle(lib,a.size)
            kernel=lib.gf_cuda_runtime_paired_change
            fp=ctypes.POINTER(ctypes.c_float)
            bp=ctypes.POINTER(ctypes.c_uint8)
            kernel.argtypes=[ctypes.c_void_p,fp,fp,bp,fp,fp,bp,ctypes.c_size_t,
                             ctypes.c_float,bp,bp]
            kernel.restype=ctypes.c_int
            if kernel(owner,_pointer(a,ctypes.c_float),_pointer(b,ctypes.c_float),
                      _pointer(av,ctypes.c_uint8),_pointer(c,ctypes.c_float),
                      _pointer(d,ctypes.c_float),_pointer(bv,ctypes.c_uint8),
                      a.size,threshold,_pointer(labels,ctypes.c_uint8),
                      _pointer(valid,ctypes.c_uint8))<0:
                raise RuntimeError("CUDA paired change failed.")
            return labels,valid.astype(bool),"cuda-spectral-fused",["cuda-spectral"]*2
        except (RuntimeError,ValueError,MemoryError,AttributeError):
            if not automatic:
                raise
            logging.getLogger(__name__).warning("CUDA fused pipeline unavailable; using regular spectral path.")
    x,xv,xe=normalized_difference(a,b,av)
    y,yv,ye=normalized_difference(c,d,bv)
    labels,engine=classify_change(x,xv,y,yv,threshold)
    return labels,xv&yv,engine,[xe,ye]
