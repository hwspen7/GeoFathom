"""Optional CUDA backend with demand-grown reusable device buffers."""
import atexit
import ctypes
import os
from threading import RLock

_lock=RLock()
_owner=None
_library=None

def _close():
    global _owner,_library
    with _lock:
        if _owner:
            _library.gf_cuda_runtime_destroy(_owner)
        _owner=None
        _library=None

atexit.register(_close)

def handle(lib,count):
    global _owner,_library
    if not hasattr(lib,"gf_cuda_runtime_create"):
        raise RuntimeError("Native CUDA backend was not built.")
    capacity=int(os.getenv("GEOFATHOM_CUDA_SPECTRAL_MAX_PIXELS","16777216"))
    budget=int(os.getenv("GEOFATHOM_CUDA_SPECTRAL_BUDGET_MB","256"))
    if not 1<=budget<=4096:
        raise ValueError("CUDA spectral budget must be 1–4096 MiB.")
    capacity=min(capacity,budget*1024*1024//15)
    if not 1<=capacity<=16777216 or count>capacity:
        raise ValueError("CUDA spectral call exceeds the buffer capacity.")
    with _lock:
        if _owner:
            if lib is not _library:
                raise RuntimeError("Another native library already owns the CUDA runtime.")
            return _owner
        create=lib.gf_cuda_runtime_create
        create.argtypes=[ctypes.c_size_t,ctypes.c_int]
        create.restype=ctypes.c_void_p
        destroy=lib.gf_cuda_runtime_destroy
        destroy.argtypes=[ctypes.c_void_p]
        destroy.restype=None
        _owner=create(capacity,int(os.getenv("GEOFATHOM_CUDA_DEVICE_ID","0")))
        if not _owner:
            raise RuntimeError("CUDA allocation failed.")
        _library=lib
        return _owner

def trim():
    """Release idle device buffers without invalidating the shared handle."""
    with _lock:
        if _owner:
            fn=_library.gf_cuda_runtime_trim
            fn.argtypes=[ctypes.c_void_p];fn.restype=ctypes.c_int
            if fn(_owner)!=0:raise RuntimeError("CUDA buffer trim failed.")

def stats():
    with _lock:
        if not _owner:return {"capacity_pixels":0,"limit_pixels":0,"allocated_bytes":0}
        fn=_library.gf_cuda_runtime_stats
        fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t)];fn.restype=ctypes.c_int
        out=(ctypes.c_size_t*3)()
        if fn(_owner,out)!=0:raise RuntimeError("CUDA allocation stats failed.")
        return dict(zip(("capacity_pixels","limit_pixels","allocated_bytes"),out))
