"""Optional native CUDA terrain execution; unavailable devices fall back explicitly."""
import ctypes
import os
import numpy as np
from geometry.topology import _native


def device_memory():
    lib=_native()
    if lib is None or not hasattr(lib,"gf_cuda_terrain_memory"):
        return 0,0
    fn=lib.gf_cuda_terrain_memory
    fn.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_size_t)]
    fn.restype=ctypes.c_int
    out=(ctypes.c_size_t*2)()
    try:device=int(os.getenv("GEOFATHOM_CUDA_DEVICE_ID","0"))
    except ValueError:return 0,0
    return tuple(map(int,out)) if fn(device,out)==0 else (0,0)


def gradients(z,valid,dx,dy,method,budget):
    if budget<=0:return None
    lib=_native()
    if lib is None or not hasattr(lib,"gf_cuda_terrain_gradient"):return None
    z=np.ascontiguousarray(z,dtype=np.float32)
    mask=np.ascontiguousarray(valid,dtype=np.uint8)
    if z.shape!=mask.shape or z.ndim!=2:return None
    if z.size*14>budget:return None
    east=np.empty_like(z);south=np.empty_like(z);out=np.empty_like(mask)
    f=ctypes.POINTER(ctypes.c_float);u=ctypes.POINTER(ctypes.c_uint8)
    fn=lib.gf_cuda_terrain_gradient
    fn.argtypes=[ctypes.c_int,f,u,ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_double,ctypes.c_int,ctypes.c_size_t,f,f,u]
    fn.restype=ctypes.c_int
    try:device=int(os.getenv("GEOFATHOM_CUDA_DEVICE_ID","0"))
    except ValueError:return None
    status=fn(device,z.ctypes.data_as(f),mask.ctypes.data_as(u),
              z.shape[1],z.shape[0],dx,dy,0 if method=="horn" else 1,budget,
              east.ctypes.data_as(f),south.ctypes.data_as(f),out.ctypes.data_as(u))
    return (east,south,out.astype(bool)) if status==0 else None
