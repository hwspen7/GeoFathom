"""Reusable C++ BVH index of projected segments, with a Shapely fallback.

One index answers many nearest-edge queries without rescanning all lines.
The Python owner is responsible for the lifecycle of the native handle.
"""
import ctypes
import math
from contextlib import contextmanager
from threading import Condition, RLock, local

import numpy as np
from shapely.geometry import Point, LineString
from shapely.strtree import STRtree

from .measure import GeometryError
from .topology import _native


class SegmentIndex:
    def __init__(self, segments: list[tuple[tuple[float,float],tuple[float,float]]]):
        if not 1 <= len(segments) <= 1_000_000:
            raise GeometryError("Provide between 1 and 1,000,000 projected segments.")
        # The original segment list is not retained: C++ copies coordinates
        # into the immutable BVH, and Shapely owns its own line geometries.
        self._condition=Condition(RLock())
        self._readers=0
        self._reader_depth=local()
        self._closed=False
        self._handle=None
        self._library=_native()
        self._tree=None
        self._lines=None
        try:
            packed=np.asarray(segments,dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise GeometryError("Segments require numeric XY endpoints.") from error
        if (packed.shape!=(len(segments),2,2) or
                not np.isfinite(packed).all() or
                np.any(np.abs(packed)>1e12)):
            raise GeometryError("Segments must have finite bounded metric XY coordinates.")
        # C++ clones the inputs into owned BVH storage, so the contiguous
        # NumPy buffer can be released immediately after native construction.
        packed=np.ascontiguousarray(packed)
        if self._library is not None and hasattr(self._library,"gf_spatial_index_build"):
            lib=self._library
            builder=lib.gf_spatial_index_build
            builder.argtypes=[ctypes.POINTER(ctypes.c_double),ctypes.c_size_t]
            builder.restype=ctypes.c_void_p
            self._handle=builder(
                packed.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                len(segments))
            if not self._handle: raise GeometryError("C++ spatial index allocation failed.")
            self.engine="cpp-bvh"
        else:
            self._lines=[LineString((a,b)) for a,b in packed]
            self._tree=STRtree(self._lines)
            self.engine="shapely-strtree"

    def close(self):
        # Block new queries, then wait for active readers to finish.
        with self._condition:
            if self._closed and not self._handle:
                return
            self._closed=True
            while self._readers:
                self._condition.wait()
            if self._handle:
                fn=self._library.gf_spatial_index_destroy
                fn.argtypes=[ctypes.c_void_p]
                fn.restype=None
                fn(self._handle)
                self._handle=None

    @contextmanager
    def _lease(self):
        with self._condition:
            depth=getattr(self._reader_depth,"value",0)
            if self._closed and depth==0:
                raise GeometryError("Spatial index is closed.")
            self._readers+=1
            self._reader_depth.value=depth+1
        try:
            yield
        finally:
            with self._condition:
                self._reader_depth.value-=1
                self._readers-=1
                if self._readers==0:
                    self._condition.notify_all()

    def __del__(self):
        # Releasing the owner also releases native resources if a caller
        # neglects to use the preferred context-manager lifecycle.
        if getattr(self,"_handle",None):
            try:self.close()
            except Exception:pass

    def __enter__(self):
        with self._condition:
            if self._closed:
                raise GeometryError("Spatial index is closed.")
        return self
    def __exit__(self,*args): self.close()

    def query(self,x:float,y:float,tolerance_m:float):
        with self._lease():
            if (not all(math.isfinite(v) for v in (x,y,tolerance_m))
                    or max(abs(x),abs(y))>1e12 or
                    not 0<=tolerance_m<=1e9):
                raise GeometryError("Query needs finite metric coordinates and nonnegative tolerance.")
            if self._handle:
                fn=self._library.gf_spatial_index_query
                fn.argtypes=[
                    ctypes.c_void_p,ctypes.c_double,ctypes.c_double,
                    ctypes.c_double,ctypes.POINTER(ctypes.c_double),
                ]
                fn.restype=ctypes.c_int
                result=(ctypes.c_double*4)()
                status=fn(self._handle,x,y,tolerance_m,result)
                if status<0: raise GeometryError("Native index query failed.")
                if status==0: return None
                return {"segment":int(result[3]),"point":(float(result[0]),float(result[1])),
                        "distance_m":float(result[2])}
            p=Point(x,y)
            best=None
            # STRtree query filters by a bounding square before precise projection.
            bounds=p if tolerance_m == 0 else p.buffer(tolerance_m).envelope
            for index in self._tree.query(bounds):
                i=int(index)
                line=self._lines[i]
                d=line.distance(p)
                if d<=tolerance_m and (best is None or d<best["distance_m"]):
                    hit=line.interpolate(line.project(p))
                    best={"segment":i,"point":(hit.x,hit.y),"distance_m":d}
            return best

    def query_many(self, positions, tolerance_m: float):
        with self._lease():
            """Batch projected XY queries, preserving per-point no-match results."""
            if not math.isfinite(tolerance_m) or not 0<=tolerance_m<=1e9:
                raise GeometryError("Batch tolerance must be finite and nonnegative.")
            try:
                pairs=np.asarray(positions,dtype=np.float64)
            except (TypeError, ValueError) as error:
                raise GeometryError("Batch queries require finite XY pairs.") from error
            if (pairs.ndim != 2 or pairs.shape[1] != 2 or
                    not 1 <= len(pairs) <= 100000 or not np.isfinite(pairs).all()
                    or np.any(np.abs(pairs)>1e12)):
                raise GeometryError("Batch queries require 1–100,000 finite XY pairs.")
            pairs=np.ascontiguousarray(pairs)
            if self._handle and hasattr(self._library,"gf_spatial_index_query_batch"):
                fn=self._library.gf_spatial_index_query_batch
                fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,ctypes.c_double,ctypes.POINTER(ctypes.c_double),
                    ctypes.POINTER(ctypes.c_uint8)]
                fn.restype=ctypes.c_int
                records=np.zeros((len(pairs),4),dtype=np.float64)
                matched=np.zeros(len(pairs),dtype=np.uint8)
                count=fn(self._handle,
                    pairs.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                    len(pairs),tolerance_m,
                    records.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                    matched.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)))
                if count<0:
                    raise GeometryError("Native spatial batch query failed.")
                return [None if not matched[i] else {
                    "segment":int(records[i,3]),
                    "point":(float(records[i,0]),float(records[i,1])),
                    "distance_m":float(records[i,2]),
                } for i in range(len(pairs))]
            return [self.query(float(x),float(y),tolerance_m) for x,y in pairs]
