"""Bounded-memory area and Horn slope statistics with exact pixel halos.

Use this only when the selected window exceeds the in-memory C++ analysis
budget. The 3x3 halo is clipped to the requested study window, not the entire
source raster, so the same neighborhoods contribute as in the small-grid path.
"""
import math

import numpy as np
from rasterio.features import geometry_mask
from rasterio.windows import Window

from imagery.raster import RasterError
from .cancellation import checkpoint
from .compute_resources import active_limits

_BLOCK=512


def analyze_area_tiled(source, polygon, window, cancel=None,gradient_method="horn"):
    if gradient_method not in {"horn","zevenbergen_thorne"}:
        raise RasterError("Unsupported terrain gradient method.")
    """Compute complete-window terrain statistics with at most 514x514 pixels."""
    limits=active_limits()
    block=limits.tile_size if limits is not None else _BLOCK
    height,width=int(window.height),int(window.width)
    if height<3 or width<3:
        raise RasterError("Slope analysis requires at least a 3 x 3 study area.")
    elevation_sum=0.
    valid_pixels=0
    elevation_min=math.inf
    elevation_max=-math.inf
    slope_sum=0.
    slope_pixels=0
    slope_max=0.
    downslope_sine=0.
    downslope_cosine=0.
    dx,dy=abs(source.transform.a),abs(source.transform.e)
    for row in range(0,height,block):
        for col in range(0,width,block):
            checkpoint(cancel)
            h=min(block,height-row)
            w=min(block,width-col)
            # Read one extra pixel around the core. This avoids seams while
            # preserving all source-window and study-polygon boundaries.
            hr0=max(0,row-1)
            hr1=min(height,row+h+1)
            hc0=max(0,col-1)
            hc1=min(width,col+w+1)
            halo=Window(window.col_off+hc0,window.row_off+hr0,
                        hc1-hc0,hr1-hr0)
            samples=source.read(1,window=halo,masked=True).astype(np.float32)
            within=geometry_mask([polygon],out_shape=samples.shape,
                                 transform=source.window_transform(halo),
                                 invert=True)
            heights=np.asarray(samples.filled(np.nan),dtype=np.float32)
            valid=within & ~np.ma.getmaskarray(samples) & np.isfinite(heights)
            core_rows=slice(row-hr0,row-hr0+h)
            core_cols=slice(col-hc0,col-hc0+w)
            core=heights[core_rows,core_cols]
            core_valid=valid[core_rows,core_cols]
            values=core[core_valid]
            if values.size:
                valid_pixels+=int(values.size)
                elevation_sum+=float(values.astype(np.float64).sum())
                elevation_min=min(elevation_min,float(values.min()))
                elevation_max=max(elevation_max,float(values.max()))
            # Center pixels at the edge of the study window cannot supply a
            # complete 3x3 kernel, even if pixels exist outside the window.
            r0=max(row,1)
            r1=min(row+h,height-1)
            c0=max(col,1)
            c1=min(col+w,width-1)
            if r1<=r0 or c1<=c0:
                continue
            rs=slice(r0-hr0-1,r1-hr0-1)
            cs=slice(c0-hc0-1,c1-hc0-1)
            neighborhoods=np.lib.stride_tricks.sliding_window_view(heights,(3,3))[rs,cs]
            masks=np.lib.stride_tricks.sliding_window_view(valid,(3,3))[rs,cs]
            good=masks.all(axis=(-2,-1)) & np.isfinite(neighborhoods).all(axis=(-2,-1))
            if not good.any():
                continue
            # The Horn derivative matches the small-grid NumPy fallback.
            p=neighborhoods
            if gradient_method=="horn":
                east=(p[:,:,0,2]+2*p[:,:,1,2]+p[:,:,2,2]
                      -p[:,:,0,0]-2*p[:,:,1,0]-p[:,:,2,0])/(8*dx)
                south=(p[:,:,2,0]+2*p[:,:,2,1]+p[:,:,2,2]
                       -p[:,:,0,0]-2*p[:,:,0,1]-p[:,:,0,2])/(8*dy)
            else:
                east=(p[:,:,1,2]-p[:,:,1,0])/(2*dx)
                south=(p[:,:,2,1]-p[:,:,0,1])/(2*dy)
            gradient=np.hypot(east,south)
            angles=np.degrees(np.arctan(gradient))[good]
            slope_pixels+=int(angles.size)
            slope_sum+=float(angles.astype(np.float64).sum())
            slope_max=max(slope_max,float(angles.max()))
            bearings=np.arctan2(-east[good],south[good])
            bearings=bearings[gradient[good]>1e-12]
            downslope_sine+=float(np.sin(bearings).sum())
            downslope_cosine+=float(np.cos(bearings).sum())
    if valid_pixels<9:
        raise RasterError("Not enough valid DEM elevation cells.")
    if not slope_pixels:
        raise RasterError("DEM contains no valid 3x3 slope neighborhoods.")
    bearing=(float(math.degrees(math.atan2(downslope_sine,downslope_cosine))%360)
             if math.hypot(downslope_sine,downslope_cosine)>1e-8 else None)
    return {
        "elevation_min_m":elevation_min,
        "elevation_max_m":elevation_max,
        "elevation_mean_m":elevation_sum/valid_pixels,
        "elevation_relief_m":elevation_max-elevation_min,
        "valid_pixels":valid_pixels,
        "mean_slope_deg":slope_sum/slope_pixels,
        "mean_aspect_deg":bearing,
        "gradient_pixels":slope_pixels,
        "maximum_slope_deg":slope_max,
        "engine":"numpy-tiled-"+gradient_method,
    }
