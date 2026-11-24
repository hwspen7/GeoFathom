"""Bounded multi-neighborhood TRI/TPI, preserving source-grid NoData.

The neighborhood-size choice has a physical interpretation in DEM cell units;
it is not an interpolation or a presentation-only setting.
"""
import numpy as np
from imagery.raster import RasterError
from .cancellation import checkpoint


def multiscale_terrain(z,valid,radius,operation,cancel=None,block=192):
    if operation not in {"tri","tpi"}:
        raise RasterError("Multi-scale neighborhood supports only TRI and TPI.")
    if not isinstance(radius,int) or not 1<=radius<=4:
        raise RasterError("Neighborhood radius must be 1–4 cells.")
    z=np.asarray(z,dtype=np.float64)
    valid=np.asarray(valid,dtype=bool)
    if z.ndim!=2 or valid.shape!=z.shape or min(z.shape)<2*radius+1:
        raise RasterError("DEM is too small for selected neighborhood.")
    result=np.full(z.shape,np.nan,dtype=np.float64)
    width=2*radius+1
    count=width*width-1
    for row in range(radius,z.shape[0]-radius,block):
        stop_row=min(z.shape[0]-radius,row+block)
        for col in range(radius,z.shape[1]-radius,block):
            checkpoint(cancel)
            stop_col=min(z.shape[1]-radius,col+block)
            tile=z[row-radius:stop_row+radius,col-radius:stop_col+radius]
            mask=valid[row-radius:stop_row+radius,col-radius:stop_col+radius]
            cells=np.lib.stride_tricks.sliding_window_view(tile,(width,width))
            masks=np.lib.stride_tricks.sliding_window_view(mask,(width,width))
            complete=masks.all(axis=(-1,-2))
            center=z[row:stop_row,col:stop_col]
            if operation=="tpi":
                neighbors=(cells.sum(axis=(-1,-2))-center)/count
                values=center-neighbors
            else:
                differences=cells-center[...,None,None]
                values=np.sqrt(np.square(differences).sum(axis=(-1,-2)))
            result[row:stop_row,col:stop_col]=np.where(complete,values,np.nan)
    if not np.isfinite(result).any():
        raise RasterError("No complete terrain neighborhoods at selected scale.")
    return result
