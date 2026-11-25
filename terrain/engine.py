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
from .compute_resources import current_limits, active_limits

_GEOD=Geod(ellps="WGS84")


def _check_dem(src):
    if not src.crs or not src.crs.is_projected or src.crs.linear_units.lower() not in {"metre","meter","metres","meters"}:
        raise RasterError("DEM terrain analysis requires projected horizontal coordinates in meters.")
    if src.count!=1:raise RasterError("DEM needs exactly one elevation band.")
    # A slope/aspect/flow raster is a valid GeoTIFF, but not an absolute
    # elevation surface. Do not silently interpret its float32 pixels as DEM.
    # Only an exported absolute elevation grid may be reused as terrain input.
    operation=src.tags().get("TERRAIN_OPERATION")
    if operation and operation!="elevation":
        raise RasterError("Derived terrain products are not source DEM elevations; select an elevation raster.")
    derived_unit=src.tags().get("TERRAIN_UNIT")
    if derived_unit and derived_unit!="m":
        raise RasterError("Source DEM elevations must have meter-valued raster cells.")
    # Rasterio reads raw sample values, not scaled physical heights. Reject
    # non-identity band transforms to avoid silent errors in slope and volume.
    if not math.isclose(float(src.scales[0]),1.,rel_tol=0,abs_tol=1e-12) or not math.isclose(float(src.offsets[0]),0.,rel_tol=0,abs_tol=1e-12):
        raise RasterError("Scaled DEM bands are unsupported: convert band scale/offset to physical meter elevations before analysis.")
    # Band-unit and dataset-tag metadata are independent assertions. A
    # declared meter band must not silently override a conflicting foot tag.
    for unit in (src.units[0],src.tags().get("VERTICAL_UNIT","")):
        if unit and unit.strip().lower() not in {"m","metre","meter","metres","meters"}:
            raise RasterError("DEM vertical units must be meters.")
    # The presence of two incompatible declared vertical datums must also
    # fail closed, including for simple slope/profile operations.
    from .vertical import vertical_datum
    vertical_datum(src)
    if abs(src.transform.b)>1e-9 or abs(src.transform.d)>1e-9:
        raise RasterError("DEM must be north-up; rectify rotated imagery before analysis.")
    if src.transform.a<=0 or src.transform.e>=0:
        raise RasterError("Unsupported DEM orientation.")
    if src.width>20000 or src.height>20000:
        raise RasterError("DEM image dimensions are too large.")
    # Meters printed on a map's grid are not guaranteed to be ground meters.
    # At middle latitudes, Web Mercator overstates horizontal distances by
    # tens of percent and silently corrupts slope/area/volume statistics.
    from .projection import grid_scale_error_percent
    grid_scale_error_percent(src)
    # The actual vertical unit cannot be inferred for an arbitrary GeoTIFF.
    # The caller explicitly asserts that the first band contains meter heights.


def _native_slope(array,valid,dx,dy,gradient_method="horn"):
    if gradient_method not in {"horn","zevenbergen_thorne"}:
        raise RasterError("Unsupported terrain gradient method.")
    z=np.ascontiguousarray(array.astype(np.float32))
    mask=np.ascontiguousarray(valid.astype(np.uint8))
    lib=_native()
    if gradient_method=="horn" and lib is not None and hasattr(lib,"gf_dem_gradient"):
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
    if gradient_method=="horn":
        e=(p[:,:,0,2]+2*p[:,:,1,2]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,1,0]-p[:,:,2,0])/(8*dx)
        s=(p[:,:,2,0]+2*p[:,:,2,1]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,0,1]-p[:,:,0,2])/(8*dy)
    else:
        e=(p[:,:,1,2]-p[:,:,1,0])/(2*dx)
        s=(p[:,:,2,1]-p[:,:,0,1])/(2*dy)
    gradients=np.hypot(e,s)
    angle=np.degrees(np.arctan(gradients))[good]
    if not angle.size:raise RasterError("DEM contains no valid 3×3 slope neighborhoods.")
    downhill=np.arctan2(-e[good],s[good])
    downhill=downhill[gradients[good]>1e-12]
    aspect=(float(np.degrees(np.arctan2(np.sin(downhill).sum(),np.cos(downhill).sum()))%360)
            if downhill.size else None)
    return {"mean_slope_deg":float(angle.mean()),"mean_aspect_deg":aspect,
            "gradient_pixels":int(angle.size),"maximum_slope_deg":float(angle.max()),
            "engine":"numpy-"+gradient_method}


def analyze_area(path,geometry,vertical_unit="meter",gradient_method="horn",cancel=None):
    if gradient_method not in {"horn","zevenbergen_thorne"}:
        raise RasterError("Unsupported terrain gradient method.")
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
        limits=current_limits()
        side=32768 if active_limits() else 8192
        if w.width<3 or w.height<3 or w.width>side or w.height>side or w.width*w.height>limits.slope_cells:
            raise RasterError(f"Slope analysis supports up to {limits.slope_cells:,} pixels and {side:,} pixels per side under the effective compute budget. Adjust Settings or select a smaller region.")
        # Device path is confined to bounded grids; large rasters remain tiled.
        # Preserve exact CPU fallback if the native CUDA library/device is absent.
        # Keep the high-performance C++ Horn kernel for small study areas.
        # Large windows use exactly overlapping 3x3 NumPy blocks and do not
        # allocate an 8+ million-cell elevation/mask array in one piece.
        if w.width>4096 or w.height>4096 or w.width*w.height>limits.native_slope_cells:
            from .tiled import analyze_area_tiled
            result=analyze_area_tiled(src,polygon,w,cancel,gradient_method=gradient_method)
            return {
                "source":"User-provided projected GeoTIFF DEM",
                "source_crs":str(src.crs),"vertical_unit":"meter",
                "cell_resolution_m":[abs(src.transform.a),abs(src.transform.e)],
                **result,
                "warning":f"Slope and aspect use complete 3x3 {gradient_method} neighborhoods "
                          "with one-pixel halos across processing tiles; "
                          "DEM vertical units and datum must be verified. Not survey-grade.",
            }
        values=src.read(1,window=w,masked=True).astype(np.float32)
        cover=geometry_mask([polygon],out_shape=values.shape,
                            transform=src.window_transform(w),invert=True)
        usable=(cover&~np.ma.getmaskarray(values)&np.isfinite(np.asarray(values)))
        heights=np.asarray(values.filled(np.nan),dtype=np.float32)
        valid_values=heights[usable]
        if len(valid_values)<9:raise RasterError("Not enough valid DEM elevation cells.")
        checkpoint(cancel)
        slope=None
        if limits.gpu_memory_bytes and heights.size>=65536:
            from .cuda_terrain import gradients
            computed=gradients(heights,usable,abs(src.transform.a),abs(src.transform.e),gradient_method,limits.gpu_memory_bytes)
            if computed is not None:
                east,south,good=computed
                magnitude=np.hypot(east[good],south[good])
                if not magnitude.size:raise RasterError("DEM contains no valid 3×3 slope neighborhoods.")
                angles=np.degrees(np.arctan(magnitude))
                moving=magnitude>1e-12
                bearing=np.arctan2(-east[good][moving],south[good][moving])
                sine=float(np.sin(bearing).sum());cosine=float(np.cos(bearing).sum())
                direction=math.degrees(math.atan2(sine,cosine))%360 if math.hypot(sine,cosine)>1e-8 else None
                slope={"mean_slope_deg":float(angles.astype(np.float64).mean()),"maximum_slope_deg":float(angles.max()),
                       "mean_aspect_deg":direction,"gradient_pixels":int(angles.size),"engine":"cuda-"+gradient_method}
        if slope is None:
            slope=_native_slope(heights,usable,abs(src.transform.a),abs(src.transform.e),gradient_method)
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
            "warning":f"Slope and aspect use 3×3 {gradient_method} cells, and require a verified meter-based DEM. "
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
