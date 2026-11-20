"""Precision drawing uses C++ metric kernels and authoritative PyProj/Shapely GIS."""

import ctypes
import math
from typing import Any

from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import split, transform
from .measure import GeometryError, measure_geometry
from .topology import _native

GEOD = Geod(ellps="WGS84")


def coordinate(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
        or any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) for x in value)
        or not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90):
        raise GeometryError("A finite WGS84 longitude/latitude pair is required.")
    return float(value[0]), float(value[1])


def projection(origin):
    lon, lat = coordinate(origin)
    if abs(lat) >= 85:
        raise GeometryError("Polar editing needs a polar projection.")
    crs = f"+proj=aeqd +lat_0={lat:.9f} +lon_0={lon:.9f} +datum=WGS84 +units=m +no_defs"
    return (Transformer.from_crs("EPSG:4326",crs,always_xy=True),
            Transformer.from_crs(crs,"EPSG:4326",always_xy=True))


def construct(mode, vertices, radius_m=None, bearing_deg=None, length_m=None, segments=72):
    vertices = [coordinate(p) for p in vertices]
    if mode == "polygon":
        if len(vertices) < 3 or len(vertices) > 4001:
            raise GeometryError("Polygon needs 3–4,001 coordinates.")
        result = mapping(Polygon(vertices))
    elif mode == "rectangle":
        if len(vertices) != 2:
            raise GeometryError("Rectangle needs two opposite corners.")
        a,b = vertices
        west,east = sorted((a[0],b[0]))
        south,north = sorted((a[1],b[1]))
        if east == west or north == south or east-west > 170:
            raise GeometryError("Rectangle has zero area or crosses the antimeridian.")
        result = mapping(Polygon([(west,south),(east,south),(east,north),(west,north)]))
    elif mode == "circle":
        if len(vertices) != 1 or radius_m is None or not math.isfinite(radius_m) or not 0 < radius_m <= 100000 or not 16 <= segments <= 360:
            raise GeometryError("Circle needs a center and radius <=100 km with 16–360 segments.")
        lon,lat=vertices[0]
        ring=[GEOD.fwd(lon,lat,360*i/segments,radius_m)[:2] for i in range(segments)]
        result=mapping(Polygon(ring))
    elif mode == "bearing":
        if len(vertices) != 1 or bearing_deg is None or length_m is None or not math.isfinite(bearing_deg) or not math.isfinite(length_m) or not 0 < length_m <= 100000:
            raise GeometryError("Bearing tool needs origin, heading and valid length.")
        lon,lat=vertices[0]
        x,y,_=GEOD.fwd(lon,lat,bearing_deg,length_m)
        result={"type":"LineString","coordinates":[[lon,lat],[x,y]]}
    else:
        raise GeometryError("Unknown shape construction mode.")
    return {"geometry":result,"measurement":measure_geometry(result),"construction":mode}


def validate(geometry):
    try:
        return {"valid":True,"measurement":measure_geometry(geometry),"message":"Geometry is valid."}
    except GeometryError as error:
        return {"valid":False,"measurement":None,"message":str(error)}


def snap(coordinate_pair, paths, tolerance_m):
    origin=coordinate(coordinate_pair)
    if not math.isfinite(tolerance_m) or not 0 <= tolerance_m <= 500 or len(paths)>100:
        raise GeometryError("Snap tolerance must be 0–500 meters and at most 100 paths.")
    fw,bw=projection(origin)
    lib=_native()
    best_distance=tolerance_m
    best=None
    mode="python"
    for path in paths:
        if not 1 <= len(path) <= 4000:
            raise GeometryError("Snap paths must contain 1–4,000 coordinates.")
        pts=[coordinate(p) for p in path]
        closed=len(pts)>=4 and pts[0]==pts[-1]
        if closed: pts.pop()
        xy=[fw.transform(*p) for p in pts]
        if lib is not None and hasattr(lib,"gf_snap_point"):
            fn=lib.gf_snap_point
            fn.argtypes=[ctypes.POINTER(ctypes.c_double),ctypes.c_size_t,ctypes.c_int,
                         ctypes.c_double,ctypes.c_double,ctypes.c_double,
                         ctypes.POINTER(ctypes.c_double)]
            fn.restype=ctypes.c_int
            flat=[v for pt in xy for v in pt]
            arr=(ctypes.c_double*len(flat))(*flat)
            result=(ctypes.c_double*3)()
            kind=fn(arr,len(xy),int(closed),0,0,tolerance_m,result)
            if kind<0: raise GeometryError("Native snapping failed.")
            if kind and result[2]<best_distance:
                best_distance=float(result[2])
                best=(bw.transform(result[0],result[1]),"vertex" if kind==1 else "edge")
                mode="cpp"
        else:
            for pt in xy:
                dist=math.hypot(*pt)
                if dist<best_distance:
                    best_distance=dist
                    best=(bw.transform(*pt),"vertex")
            if len(xy)>1:
                line=LineString(xy + xy[:1] if closed else xy)
                nearest=line.interpolate(line.project(Point(0,0)))
                dist=math.hypot(nearest.x,nearest.y)
                if dist<best_distance:
                    best_distance=dist
                    best=(bw.transform(nearest.x,nearest.y),"edge")
    return {"coordinate":list(best[0] if best else origin),
            "snapped":best is not None,"kind":best[1] if best else "none",
            "distance_m":best_distance if best else None,"engine":mode}


def simplify(vertices,tolerance_m):
    if not math.isfinite(tolerance_m) or not 0 <= tolerance_m <= 500 or not 2 <= len(vertices) <= 20000:
        raise GeometryError("Simplification requires 2–20,000 points, tolerance 0–500 m.")
    coords=[coordinate(p) for p in vertices]
    fw,_=projection(coords[0])
    xy=[fw.transform(*p) for p in coords]
    lib=_native()
    if lib is not None and hasattr(lib,"gf_simplify_line"):
        fn=lib.gf_simplify_line
        fn.argtypes=[ctypes.POINTER(ctypes.c_double),ctypes.c_size_t,ctypes.c_double,ctypes.POINTER(ctypes.c_size_t)]
        fn.restype=ctypes.c_int
        arr=(ctypes.c_double*(len(xy)*2))(*(v for pt in xy for v in pt))
        indices=(ctypes.c_size_t*len(xy))()
        length=fn(arr,len(xy),tolerance_m,indices)
        if length<2: raise GeometryError("Native simplification failed.")
        keep=[indices[i] for i in range(length)]
        engine="cpp"
    else:
        line=LineString(xy).simplify(tolerance_m,preserve_topology=False)
        keep=sorted(set(min(range(len(xy)),key=lambda i:math.dist(xy[i],p)) for p in line.coords))
        engine="shapely"
    return {"vertices":[list(coords[i]) for i in keep],"retained":len(keep),"engine":engine}


def polygon_split(polygon,cutter):
    measure_geometry(polygon)
    measure_geometry(cutter)
    a,b=shape(polygon),shape(cutter)
    if a.geom_type not in {"Polygon","MultiPolygon"} or b.geom_type not in {"LineString","MultiLineString"}:
        raise GeometryError("A polygon and a cutting line are required.")
    if a.bounds[2]-a.bounds[0]>170: raise GeometryError("Antimeridian split unsupported.")
    pieces=[mapping(x) for x in split(a,b).geoms if x.geom_type=="Polygon" and not x.is_empty]
    if len(pieces)<2: raise GeometryError("Cutting line did not divide the polygon.")
    return {"features":[{"geometry":x,"measurement":measure_geometry(x)} for x in pieces]}


def polygon_hole(polygon,hole):
    measure_geometry(polygon)
    measure_geometry(hole)
    a,b=shape(polygon),shape(hole)
    if a.geom_type not in {"Polygon","MultiPolygon"} or b.geom_type not in {"Polygon","MultiPolygon"} or not a.contains(b):
        raise GeometryError("A polygon hole must be strictly inside its parent.")
    out=mapping(a.difference(b))
    return {"geometry":out,"measurement":measure_geometry(out)}


def move(geometry,bearing_deg,distance_m):
    measure_geometry(geometry)
    if not math.isfinite(bearing_deg) or not math.isfinite(distance_m) or not 0 <= distance_m <= 100000:
        raise GeometryError("Move distance must be 0–100 km and heading finite.")
    def shift(x,y,z=None):
        import numpy as np
        xx,yy,_=GEOD.fwd(x,y,np.full_like(x,bearing_deg),np.full_like(x,distance_m))
        return (xx,yy) if z is None else (xx,yy,z)
    out=mapping(transform(shift,shape(geometry)))
    return {"geometry":out,"measurement":measure_geometry(out)}
