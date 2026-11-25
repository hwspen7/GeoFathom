"""SIMD mask boundary counting with exact scalar/NumPy parity."""
import ctypes
import numpy as np
from .topology import _native

def count_transitions(labels):
    arr=np.asarray(labels)
    if arr.ndim!=2 or arr.dtype!=np.uint8 or not 0<arr.size<=16777216:
        raise ValueError("Expected a bounded 2D uint8 label array.")
    arr=np.ascontiguousarray(arr)
    lib=_native()
    if lib is not None and hasattr(lib,"gf_mask_transitions"):
        fn=lib.gf_mask_transitions
        fn.argtypes=[ctypes.POINTER(ctypes.c_uint8),ctypes.c_size_t,ctypes.c_size_t]
        fn.restype=ctypes.c_int
        value=fn(arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),arr.shape[1],arr.shape[0])
        if value<0:
            raise ValueError("Native transition count rejected the mask.")
        return value
    return int(np.count_nonzero(arr[:,1:]!=arr[:,:-1])+
               np.count_nonzero(arr[1:,:]!=arr[:-1,:]))
