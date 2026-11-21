"""Borrow CUDA OrtValue buffers without copying model logits to host.

Native operations are synchronous and all OrtValue owners remain alive.
The GPU output class and confidence arrays are copied only at the GIS
boundary. No user-supplied pointers are accepted by the public API.
"""
import ctypes
import numpy as np
from imagery.raster import RasterError

def decode_cuda_logits(value,batch,classes,size,device_id):
    from geometry.topology import _native
    import onnxruntime as ort
    lib=_native()
    if lib is None or not hasattr(lib,"gf_cuda_device_semantic"):
        raise RuntimeError("Native CUDA model postprocessing is unavailable.")
    shape=tuple(value.shape())
    dtype=value.data_type()
    if value.device_name().lower()!="cuda":
        raise RasterError("ONNX output was not placed on CUDA.")
    if shape==(batch,classes,size,size) and dtype=="tensor(float)":
        kind=0
    elif shape==(batch,size,size) and dtype in ("tensor(int64)","tensor(int32)","tensor(uint8)"):
        kind={"tensor(int64)":1,"tensor(int32)":2,"tensor(uint8)":3}[dtype]
    else:
        raise RasterError("CUDA postprocessing requires float32 logits or int64/int32/uint8 class IDs.")
    output_shape=(batch,size,size)
    labels=ort.OrtValue.ortvalue_from_shape_and_type(output_shape,np.uint8,"cuda",device_id)
    conf=ort.OrtValue.ortvalue_from_shape_and_type(output_shape,np.float32,"cuda",device_id)
    fn=lib.gf_cuda_device_semantic
    fn.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,
                 ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p]
    fn.restype=ctypes.c_int
    if fn(device_id,value.data_ptr(),batch,size*size,classes,kind,labels.data_ptr(),conf.data_ptr()):
        raise RuntimeError("Native CUDA model postprocessing failed.")
    # No full logits transfer. OrtValue.numpy() copies only the compact outputs.
    result,confidence=labels.numpy(),conf.numpy()
    if (result.shape!=output_shape or confidence.shape!=output_shape
            or np.any(result>=classes) or not np.isfinite(confidence).all()):
        raise RasterError("Model output contains nonfinite predictions or invalid class IDs.")
    return result,confidence
