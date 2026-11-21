"""Optional CUDA backend with a fixed reusable device allocation."""
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
    capacity=int(os.getenv("GEOFATHOM_CUDA_SPECTRAL_MAX_PIXELS","1048576"))
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
