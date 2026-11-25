"""Bounded-memory slope statistics using exact halo tiles and durable reductions."""
import math
from contextlib import nullcontext

import numpy as np
from rasterio.features import geometry_mask
from rasterio.windows import Window

from imagery.raster import RasterError
from .cancellation import checkpoint
from .compute_resources import active_limits

_BLOCK=512
_RESUME_MIN_CELLS=1_000_000


def _tile(source,polygon,window,row,col,block,method):
    height,width=int(window.height),int(window.width)
    h,w=min(block,height-row),min(block,width-col)
    hr0,hr1=max(0,row-1),min(height,row+h+1)
    hc0,hc1=max(0,col-1),min(width,col+w+1)
    halo=Window(window.col_off+hc0,window.row_off+hr0,hc1-hc0,hr1-hr0)
    samples=source.read(1,window=halo,masked=True).astype(np.float32)
    within=geometry_mask([polygon],out_shape=samples.shape,
                         transform=source.window_transform(halo),invert=True)
    heights=np.asarray(samples.filled(np.nan),dtype=np.float32)
    valid=within & ~np.ma.getmaskarray(samples) & np.isfinite(heights)
    rs=slice(row-hr0,row-hr0+h);cs=slice(col-hc0,col-hc0+w)
    values=heights[rs,cs][valid[rs,cs]]
    stats=[int(values.size),float(values.astype(np.float64).sum()),
           float(values.min()) if values.size else None,
           float(values.max()) if values.size else None,0,0.,0.,0.,0.]
    # Only complete neighborhoods within the selected source window count.
    r0,r1=max(row,1),min(row+h,height-1)
    c0,c1=max(col,1),min(col+w,width-1)
    if r1<=r0 or c1<=c0:return stats
    rs=slice(r0-hr0-1,r1-hr0-1);cs=slice(c0-hc0-1,c1-hc0-1)
    p=np.lib.stride_tricks.sliding_window_view(heights,(3,3))[rs,cs]
    masks=np.lib.stride_tricks.sliding_window_view(valid,(3,3))[rs,cs]
    good=masks.all(axis=(-2,-1)) & np.isfinite(p).all(axis=(-2,-1))
    if not good.any():return stats
    dx,dy=abs(source.transform.a),abs(source.transform.e)
    if method=="horn":
        east=(p[:,:,0,2]+2*p[:,:,1,2]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,1,0]-p[:,:,2,0])/(8*dx)
        south=(p[:,:,2,0]+2*p[:,:,2,1]+p[:,:,2,2]-p[:,:,0,0]-2*p[:,:,0,1]-p[:,:,0,2])/(8*dy)
    else:
        east=(p[:,:,1,2]-p[:,:,1,0])/(2*dx)
        south=(p[:,:,2,1]-p[:,:,0,1])/(2*dy)
    gradient=np.hypot(east,south)
    angles=np.degrees(np.arctan(gradient))[good]
    bearings=np.arctan2(-east[good],south[good])[gradient[good]>1e-12]
    stats[4:]=[int(angles.size),float(angles.astype(np.float64).sum()),
               float(angles.max()),float(np.sin(bearings).sum()),float(np.cos(bearings).sum())]
    return stats


def analyze_area_tiled(source,polygon,window,cancel=None,gradient_method="horn",checkpoint_root=None):
    """Reduce source tiles without seam artifacts, resume identical interrupted studies."""
    if gradient_method not in {"horn","zevenbergen_thorne"}:
        raise RasterError("Unsupported terrain gradient method.")
    limits=active_limits()
    block=limits.tile_size if limits is not None else _BLOCK
    height,width=int(window.height),int(window.width)
    if height<3 or width<3:
        raise RasterError("Slope analysis requires at least a 3 x 3 study area.")
    checkpoint(cancel)
    if checkpoint_root is None and limits is not None and height*width>=_RESUME_MIN_CELLS:
        from imagery.store import imagery_dir
        checkpoint_root=imagery_dir()/".terrain-scratch"
    context=nullcontext(None)
    if checkpoint_root is not None:
        from .slope_checkpoints import slope_checkpoint
        context=slope_checkpoint(source,polygon,window,block,gradient_method,checkpoint_root,cancel)
    elevation_sum=slope_sum=slope_max=downslope_sine=downslope_cosine=0.
    elevation_min,elevation_max=math.inf,-math.inf
    valid_pixels=slope_pixels=ordinal=resumed=0
    with context as store:
        for row in range(0,height,block):
            for col in range(0,width,block):
                checkpoint(cancel)
                stats=store.load(ordinal) if store else None
                if stats is None:
                    stats=_tile(source,polygon,window,row,col,block,gradient_method)
                    if store:store.save(ordinal,stats)
                else:resumed+=1
                ordinal+=1
                count,total,lo,hi,grad_count,grad_sum,grad_max,sine,cosine=stats
                valid_pixels+=count
                elevation_sum+=total
                if count:
                    elevation_min=min(elevation_min,lo);elevation_max=max(elevation_max,hi)
                slope_pixels+=grad_count;slope_sum+=grad_sum;slope_max=max(slope_max,grad_max)
                downslope_sine+=sine;downslope_cosine+=cosine
        checkpoint(cancel)
        if store:store.finish()
    if valid_pixels<9:raise RasterError("Not enough valid DEM elevation cells.")
    if not slope_pixels:raise RasterError("DEM contains no valid 3x3 slope neighborhoods.")
    bearing=(float(math.degrees(math.atan2(downslope_sine,downslope_cosine))%360)
             if math.hypot(downslope_sine,downslope_cosine)>1e-8 else None)
    return {"elevation_min_m":elevation_min,"elevation_max_m":elevation_max,
            "elevation_mean_m":elevation_sum/valid_pixels,"elevation_relief_m":elevation_max-elevation_min,
            "valid_pixels":valid_pixels,"mean_slope_deg":slope_sum/slope_pixels,
            "mean_aspect_deg":bearing,"gradient_pixels":slope_pixels,"maximum_slope_deg":slope_max,
            "engine":"numpy-tiled-"+gradient_method,"tiles_processed":ordinal,"tiles_resumed":resumed}
