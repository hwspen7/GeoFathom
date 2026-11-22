"""Local projected GeoTIFF DEM slope, aspect and height-profile analysis.

No assumptions about horizontal distance in geographic degrees; sloped
statistics require a projected CRS in meters and elevation values in meters.
"""
import ctypes
import math

import numpy as np
import rasterio
from pyproj import Geod
from rasterio.features import geometry_mask
from rasterio.windows import Window,from_bounds
from rasterio.warp import transform_geom,transform
from shapely.geometry import shape

from geometry.measure import GeometryError,measure_geometry
from geometry.topology import _native
from imagery.raster import RasterError
from .cancellation import checkpoint

_GEOD=Geod(ellps="WGS84")


def _check_dem(src):
    if not src.crs or not src.crs.is_projected or src.crs.linear_units.lower() not in {"metre","meter","metres","meters"}:
        raise RasterError("DEM terrain analysis requires projected horizontal coordinates in meters.")
    if src.count!=1:raise RasterError("DEM needs exactly one elevation band.")
    unit=(src.units[0] or src.tags().get("VERTICAL_UNIT","")).strip().lower()
    if unit and unit not in {"m","metre","meter","metres","meters"}:
        raise RasterError("DEM vertical units must be meters.")
    if abs(src.transform.b)>1e-9 or abs(src.transform.d)>1e-9:
        raise RasterError("DEM must be north-up; rectify rotated imagery before analysis.")
    if src.transform.a<=0 or src.transform.e>=0:
        raise RasterError("Unsupported DEM orientation.")
    if src.width>20000 or src.height>20000:
        raise RasterError("DEM image dimensions are too large.")
    # The actual vertical unit cannot be inferred for an arbitrary GeoTIFF.
    # The caller explicitly asserts that the first band contains meter heights.


def _native_slope(array,valid,dx,dy):
    z=np.ascontiguousarray(array.astype(np.float32))
    mask=np.ascontiguousarray(valid.astype(np.uint8))
    lib=_native()
    if lib is not None and hasattr(lib,"gf_dem_gradient"):
        fn=lib.gf_dem_gradient
        fn.argtypes=[ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_uint8),
                     ctypes.c_int,ctypes.c_int,ctypes.c_double,ctypes.c_double,
                     ctypes.POINTER(ctypes.c_double)]
        fn.restype=ctypes.c_int
        out=(ctypes.c_double*4)()
        status=fn(z.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                  mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
                  z.shape[1],z.shape[0],dx,dy,out)
        if status<=0:raise RasterError("DEM contains no valid 3×3 slope neighborhoods.")
        return {"mean_slope_deg":out[0],"mean_aspect_deg":out[1] if out[1]>=0 else None,
                "gradient_pixels":int(out[2]),"maximum_slope_deg":out[3],
                "engine":"cpp-horn"}
    # Matching Horn 3x3 fallback, restricted to complete valid windows.
    p=np.lib.stride_tricks.sliding_window_view(z,(3,3))
    v=np.lib.stride_tricks.sliding_window_view(mask,(3,3))
    good=np.all(v.astype(bool),axis=(-1,-2))&np.all(np.isfinite(p),axis=(-1,-2))
    e=(p[:,:,0,2]+2*p[:,:,1,2]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,1,0]-p[:,:,2,0])/(8*dx)
    s=(p[:,:,2,0]+2*p[:,:,2,1]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,0,1]-p[:,:,0,2])/(8*dy)
    gradients=np.hypot(e,s)
    angle=np.degrees(np.arctan(gradients))[good]
    if not angle.size:raise RasterError("DEM contains no valid 3×3 slope neighborhoods.")
    downhill=np.arctan2(-e[good],s[good])
    downhill=downhill[gradients[good]>1e-12]
    aspect=(float(np.degrees(np.arctan2(np.sin(downhill).sum(),np.cos(downhill).sum()))%360)
            if downhill.size else None)
    return {"mean_slope_deg":float(angle.mean()),"mean_aspect_deg":aspect,
            "gradient_pixels":int(angle.size),"maximum_slope_deg":float(angle.max()),
            "engine":"numpy-horn"}


def analyze_area(path,geometry,vertical_unit="meter",cancel=None):
    checkpoint(cancel)
    if vertical_unit!="meter":
        raise RasterError("Terrain model currently supports vertical elevations in meters only.")
    measure_geometry(geometry)
    if geometry["type"] not in {"Polygon","MultiPolygon"}:
        raise RasterError("Elevation zone requires a polygon.")
    with rasterio.open(path) as src:
        _check_dem(src)
        polygon=transform_geom("EPSG:4326",src.crs,geometry)
        bounds=shape(polygon).bounds
        try:
            w=from_bounds(*bounds,transform=src.transform)
            left,top=math.floor(w.col_off),math.floor(w.row_off)
            right,bottom=math.ceil(w.col_off+w.width),math.ceil(w.row_off+w.height)
            w=Window(left,top,right-left,bottom-top)
            w=w.intersection(Window(0,0,src.width,src.height))
        except Exception as error:
            raise RasterError("Selected region is outside DEM raster.") from error
        if w.width<3 or w.height<3 or w.width>1024 or w.height>1024:
            raise RasterError("Select a DEM area between 3×3 and 1024×1024 source pixels.")
        values=src.read(1,window=w,masked=True).astype(np.float32)
        cover=geometry_mask([polygon],out_shape=values.shape,
                            transform=src.window_transform(w),invert=True)
        usable=(cover&~np.ma.getmaskarray(values)&np.isfinite(np.asarray(values)))
        heights=np.asarray(values.filled(np.nan),dtype=np.float32)
        valid_values=heights[usable]
        if len(valid_values)<9:raise RasterError("Not enough valid DEM elevation cells.")
        checkpoint(cancel)
        slope=_native_slope(heights,usable,abs(src.transform.a),abs(src.transform.e))
        checkpoint(cancel)
        return {
            "source":"User-provided projected GeoTIFF DEM",
            "source_crs":str(src.crs),"vertical_unit":"meter",
            "cell_resolution_m":[abs(src.transform.a),abs(src.transform.e)],
            "elevation_min_m":float(valid_values.min()),
            "elevation_max_m":float(valid_values.max()),
            "elevation_mean_m":float(valid_values.mean()),
            "elevation_relief_m":float(valid_values.max()-valid_values.min()),
            "valid_pixels":int(len(valid_values)),
            **slope,
            "warning":"Slope and aspect use 3×3 Horn cells, and require a verified meter-based DEM. "
                      "Not a survey-grade terrain model.",
        }


def elevation_profile(path,geometry,samples=80,cancel=None):
    checkpoint(cancel)
    if not 4<=samples<=250:
        raise RasterError("Profile samples must be 4–250.")
    measure_geometry(geometry)
    if geometry["type"]!="LineString":
        raise RasterError("Profile requires a line.")
    positions=geometry["coordinates"]
    if len(positions)<2:raise RasterError("Profile needs two positions.")
    with rasterio.open(path) as src:
        _check_dem(src)
        coords=[tuple(p[:2]) for p in positions]
        distance=[0.0]
        for a,b in zip(coords,coords[1:]):
            _,_,meters=_GEOD.inv(*a,*b)
            distance.append(distance[-1]+meters)
        if distance[-1]<1:raise RasterError("Profile length must exceed one meter.")
        distances=np.linspace(0,distance[-1],samples)
        interpolated=[]
        for d in distances:
            checkpoint(cancel)
            i=int(np.searchsorted(distance,d,side="right")-1)
            i=min(i,len(coords)-2)
            t=(d-distance[i])/(distance[i+1]-distance[i]) if distance[i+1]>distance[i] else 0
            bearing,_,segment=_GEOD.inv(*coords[i],*coords[i+1])
            lon,lat,_=_GEOD.fwd(*coords[i],bearing,segment*t)
            interpolated.append([lon,lat])
        xs,ys=transform("EPSG:4326",src.crs,
                        [p[0] for p in interpolated],[p[1] for p in interpolated])
        heights=[]
        locations=list(zip(xs,ys))
        for (x,y),sample in zip(locations,src.sample(locations,indexes=1,masked=True)):
            checkpoint(cancel)
            row,col=src.index(x,y);value=sample[0]
            inside=0<=row<src.height and 0<=col<src.width
            heights.append(None if not inside or np.ma.is_masked(value) or not np.isfinite(value)
                           else float(value))
        return {"samples":[{"distance_m":float(d),"elevation_m":h,"coordinate":p}
                           for d,h,p in zip(distances,heights,interpolated)],
                "length_m":float(distance[-1]),"source_crs":str(src.crs),
                "vertical_unit":"meter","warning":"Profile is sampled along the mapped line. "
                 "DEM must be verified as elevations in meters."}
