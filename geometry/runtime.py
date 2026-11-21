"""Explicit C++ worker ownership and bounded CPU parallelism."""
import atexit
import ctypes
import os
from threading import RLock

_lock=RLock()
_handle=None
_library=None


def _close():
    global _handle,_library
    with _lock:
        if _handle:
            _library.gf_cpu_runtime_destroy(_handle)
        _handle=None
        _library=None


atexit.register(_close)


def handle(lib):
    """Keep the owner alive until interpreter shutdown; no DLL static destructor."""
    global _handle,_library
    if not hasattr(lib,"gf_cpu_runtime_create"):
        return None
    with _lock:
        if _handle:
            return _handle if lib is _library else None
        threads=int(os.getenv("GEOFATHOM_NATIVE_THREADS","2"))
        if not 1<=threads<=8:
            raise ValueError("Native worker count must be 1–8.")
        create=lib.gf_cpu_runtime_create
        create.argtypes=[ctypes.c_uint]
        create.restype=ctypes.c_void_p
        destroy=lib.gf_cpu_runtime_destroy
        destroy.argtypes=[ctypes.c_void_p]
        destroy.restype=None
        _handle=create(threads)
        if not _handle:
            raise RuntimeError("Native worker runtime initialization failed.")
        _library=lib
        return _handle
