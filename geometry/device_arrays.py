"""Trusted in-process CuPy device-array interface, not an HTTP endpoint.

All normalized-index and change intermediates remain in device memory.
GDAL ingress, GIS vectorization and explicit result export are boundaries
outside this interface. Calls are synchronous for safe owner lifetimes.
"""
import ctypes
import math

def _validated(arrays,dtypes):
    import cupy as cp
    from .topology import _native
    if not arrays or any(not isinstance(a,cp.ndarray) for a in arrays):
        raise TypeError("Only owned CuPy CUDA arrays are accepted.")
    first=arrays[0];device=first.device.id
    if first.ndim!=2 or not 0<first.size<=16777216:
        raise ValueError("Invalid device raster dimensions.")
    for array,dtype in zip(arrays,dtypes):
        if (array.device.id!=device or array.shape!=first.shape
                or array.dtype!=cp.dtype(dtype) or not array.flags.c_contiguous):
            raise ValueError("Device arrays must share shape, device, type and contiguity.")
    lib=_native()
    if lib is None or not hasattr(lib,"gf_cuda_device_index"):
        raise RuntimeError("Native CUDA device-array backend is not installed.")
    return cp,lib,device,first.shape,first.size

def normalized_difference(first,second,valid):
    cp,lib,device,shape,n=_validated((first,second,valid),("float32","float32","uint8"))
    with cp.cuda.Device(device):
        out=cp.empty(shape,cp.float32);mask=cp.empty(shape,cp.uint8)
        fn=lib.gf_cuda_device_index
        fn.argtypes=[ctypes.c_int,*([ctypes.c_void_p]*3),ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p]
        fn.restype=ctypes.c_int
        if fn(device,first.data.ptr,second.data.ptr,valid.data.ptr,n,out.data.ptr,mask.data.ptr):
            raise RuntimeError("CUDA device index failed.")
    return out,mask

def classify_change(before,before_valid,after,after_valid,threshold):
    if not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<threshold<1:
        raise ValueError("Invalid device change threshold.")
    cp,lib,device,shape,n=_validated((before,before_valid,after,after_valid),
        ("float32","uint8","float32","uint8"))
    with cp.cuda.Device(device):
        labels=cp.empty(shape,cp.uint8)
        fn=lib.gf_cuda_device_change
        fn.argtypes=[ctypes.c_int,*([ctypes.c_void_p]*4),ctypes.c_size_t,ctypes.c_float,ctypes.c_void_p]
        fn.restype=ctypes.c_int
        if fn(device,before.data.ptr,before_valid.data.ptr,after.data.ptr,after_valid.data.ptr,
              n,threshold,labels.data.ptr):
            raise RuntimeError("CUDA device change failed.")
    return labels
