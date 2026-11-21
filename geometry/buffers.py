"""Bounded task-local aligned temporary buffers, with NumPy fallback.

Leased arrays are internal scratch views. They MUST NOT escape the lease
or be retained by an asynchronous consumer.
"""
from contextlib import contextmanager
import ctypes
import math
from threading import RLock
import numpy as np
from .topology import _native

class ScratchPool:
    def __init__(self,budget):
        if type(budget) is not int or not 64<=budget<=512*1024*1024:
            raise ValueError("Invalid scratch pool byte budget.")
        self.budget=budget
        self.lib=_native()
        self.owner=None
        self.active=0
        self.closed=False
        self.lock=RLock()
        if self.lib is not None and hasattr(self.lib,"gf_buffer_pool_create"):
            lib=self.lib
            lib.gf_buffer_pool_create.argtypes=[ctypes.c_size_t]
            lib.gf_buffer_pool_create.restype=ctypes.c_void_p
            lib.gf_buffer_pool_acquire.argtypes=[ctypes.c_void_p,ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_uint64),ctypes.POINTER(ctypes.c_void_p)]
            lib.gf_buffer_pool_acquire.restype=ctypes.c_int
            lib.gf_buffer_pool_release.argtypes=[ctypes.c_void_p,ctypes.c_uint64]
            lib.gf_buffer_pool_release.restype=ctypes.c_int
            lib.gf_buffer_pool_destroy.argtypes=[ctypes.c_void_p]
            lib.gf_buffer_pool_destroy.restype=ctypes.c_int
            self.owner=lib.gf_buffer_pool_create(budget)
            if not self.owner:
                raise MemoryError("Native scratch pool allocation failed.")
    @contextmanager
    def floats(self,shape):
        if not shape or any(type(n) is not int or n<1 for n in shape):
            raise ValueError("Invalid scratch tensor shape.")
        count=math.prod(shape)
        size=count*4
        # Match alignment accounting even when native code is unavailable.
        charged=((size+63)//64)*64
        lease=ctypes.c_uint64()
        ptr=ctypes.c_void_p()
        with self.lock:
            if self.closed:
                raise RuntimeError("Scratch pool is closed.")
            if charged>self.budget-self.active:
                raise MemoryError("Scratch pool byte budget exhausted.")
            if self.owner:
                if self.lib.gf_buffer_pool_acquire(self.owner,size,ctypes.byref(lease),ctypes.byref(ptr))!=0:
                    raise MemoryError("Native scratch pool byte budget exhausted.")
                try:
                    array=np.ctypeslib.as_array((ctypes.c_float*count).from_address(ptr.value)).reshape(shape)
                except Exception:
                    self.lib.gf_buffer_pool_release(self.owner,lease.value)
                    raise
            else:
                array=np.zeros(shape,np.float32)
            self.active+=charged
        try:
            yield array
        finally:
            with self.lock:
                if self.owner and self.lib.gf_buffer_pool_release(self.owner,lease.value)!=0:
                    raise RuntimeError("Invalid scratch buffer release.")
                self.active-=charged
    def close(self):
        with self.lock:
            if self.active:
                raise RuntimeError("Scratch pool has active leases.")
            if self.owner:
                if self.lib.gf_buffer_pool_destroy(self.owner)!=0:
                    raise RuntimeError("Native scratch pool still has active leases.")
                self.owner=None
            self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
