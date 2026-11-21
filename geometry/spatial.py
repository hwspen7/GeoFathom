"""Reusable C++ BVH index of projected segments, with a Shapely fallback.

One index answers many nearest-edge queries without rescanning all lines.
The Python owner is responsible for the lifecycle of the native handle.
"""
import ctypes
import math

import numpy as np
from shapely.geometry import Point, LineString
from shapely.strtree import STRtree

from .measure import GeometryError
from .topology import _native


class SegmentIndex:
    def __init__(self, segments: list[tuple[tuple[float,float],tuple[float,float]]]):
        if not 1 <= len(segments) <= 1_000_000:
            raise GeometryError("Provide between 1 and 1,000,000 projected segments.")
        self._segments=segments
        self._closed=False
        self._handle=None
        self._library=_native()
        self._tree=None
        self._lines=None
        for a,b in segments:
            if len(a)!=2 or len(b)!=2 or not all(math.isfinite(x) for x in (*a,*b)):
                raise GeometryError("Segments must have finite metric XY coordinates.")
        if self._library is not None and hasattr(self._library,"gf_spatial_index_build"):
            lib=self._library
            builder=lib.gf_spatial_index_build
            builder.argtypes=[ctypes.POINTER(ctypes.c_double),ctypes.c_size_t]
            builder.restype=ctypes.c_void_p
            flat=[x for a,b in segments for x in (*a,*b)]
            arr=(ctypes.c_double*len(flat))(*flat)
            self._handle=builder(arr,len(segments))
            if not self._handle: raise GeometryError("C++ spatial index allocation failed.")
            self.engine="cpp-bvh"
        else:
            self._lines=[LineString((a,b)) for a,b in segments]
            self._tree=STRtree(self._lines)
            self.engine="shapely-strtree"

    def close(self):
        if self._handle:
            fn=self._library.gf_spatial_index_destroy
            fn.argtypes=[ctypes.c_void_p]
            fn.restype=None
            fn(self._handle)
            self._handle=None
        self._closed=True

    def __del__(self):
        # Releasing the owner also releases native resources if a caller
        # neglects to use the preferred context-manager lifecycle.
        if getattr(self,"_handle",None):
            try:self.close()
            except Exception:pass

    def __enter__(self):
        if self._closed:
            raise GeometryError("Spatial index is closed.")
        return self
    def __exit__(self,*args): self.close()

    def query(self,x:float,y:float,tolerance_m:float):
        if self._closed:
            raise GeometryError("Spatial index is closed.")
        if not all(math.isfinite(v) for v in (x,y,tolerance_m)) or tolerance_m<0:
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
        bounds=p.buffer(tolerance_m).envelope
        for index in self._tree.query(bounds):
            i=int(index)
            line=self._lines[i]
            d=line.distance(p)
            if d<=tolerance_m and (best is None or d<best["distance_m"]):
                hit=line.interpolate(line.project(p))
                best={"segment":i,"point":(hit.x,hit.y),"distance_m":d}
        return best

    def query_many(self, positions, tolerance_m: float):
        """Batch projected XY queries, preserving per-point no-match results."""
        if self._closed:
            raise GeometryError("Spatial index is closed.")
        if not math.isfinite(tolerance_m) or tolerance_m < 0:
            raise GeometryError("Batch tolerance must be finite and nonnegative.")
        try:
            pairs=np.asarray(positions,dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise GeometryError("Batch queries require finite XY pairs.") from error
        if (pairs.ndim != 2 or pairs.shape[1] != 2 or
                not 1 <= len(pairs) <= 100000 or not np.isfinite(pairs).all()):
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
