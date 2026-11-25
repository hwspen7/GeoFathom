"""Bounded on-demand DEM tiles for camera-driven multiresolution WebGL terrain.

One call reads only a single source window, with a pixel budget and explicit
polygon mask. It does not allocate the full analysis DEM; tiles share global
cell-center coordinates and preserve the original nodata/CRS/datum.
"""
import math

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window,from_bounds
from rasterio.warp import transform_geom
from shapely.geometry import shape

from geometry.measure import measure_geometry
from imagery.raster import RasterError
from .engine import _check_dem
from .cancellation import checkpoint
from .compute_resources import active_limits


def stream_mesh_tile(path,geometry,level,tile_row,tile_col,tile_cells=32,cancel=None):
    """Return sampled vertices, measured TIN error and conservative quad mask.

    Tiles are addressed by globally aligned source raster cell indices within
    the chosen study-window. Every coarse quad touching NoData at *any* source
    pixel is omitted, even when all four sampled corner vertices are valid.
    """
    if (not isinstance(level,int) or level not in (1,2,4,8,16,32,64)
        or not isinstance(tile_cells,int) or tile_cells!=32
        or not isinstance(tile_row,int) or tile_row<0
        or not isinstance(tile_col,int) or tile_col<0):
        raise RasterError("A terrain tile requires power-of-two level, 32 cells and nonnegative tile coordinates.")
    checkpoint(cancel)
    measure_geometry(geometry)
    if geometry.get("type") not in {"Polygon","MultiPolygon"}:
        raise RasterError("Streaming mesh tiles require a polygon study area.")
    with rasterio.open(path) as src:
        _check_dem(src)
        projected=transform_geom("EPSG:4326",src.crs,geometry)
        boundary=shape(projected)
        grid=from_bounds(*boundary.bounds,transform=src.transform)
        left,top=math.floor(grid.col_off),math.floor(grid.row_off)
        right,bottom=math.ceil(grid.col_off+grid.width),math.ceil(grid.row_off+grid.height)
        try:
            window=Window(left,top,right-left,bottom-top).intersection(
                Window(0,0,src.width,src.height))
        except rasterio.errors.WindowError as e:
            raise RasterError("Streaming tile geometry is outside the DEM.") from e
        rows,cols=int(window.height),int(window.width)
        limits=active_limits()
        maximum=limits.slope_cells if limits else 8_000_000
        side=20000 if limits else 4096
        if not 2<=rows<=side or not 2<=cols<=side or rows*cols>maximum:
            raise RasterError(f"Streaming study grid exceeds effective {maximum:,}-cell/{side}-axis budget.")
        stride=level*tile_cells
        row_start=tile_row*stride
        col_start=tile_col*stride
        if row_start>=rows-1 or col_start>=cols-1:
            raise RasterError("Requested terrain tile lies outside the analysis grid.")
        row_end=min(rows-1,row_start+stride)
        col_end=min(cols-1,col_start+stride)
        checkpoint(cancel)
        part=Window(int(window.col_off)+col_start,int(window.row_off)+row_start,
                    col_end-col_start+1,row_end-row_start+1)
        if limits and part.width*part.height*96+128*1024**2>limits.memory_bytes:
            raise RasterError("Mesh tile exceeds the effective memory budget. Choose a finer LOD.")
        samples=src.read(1,window=part,masked=True).astype(np.float64)
        affine=src.window_transform(part)
        covered=geometry_mask([projected],out_shape=samples.shape,
                              transform=affine,invert=True)
        raw=np.asarray(samples.filled(np.nan),dtype=np.float64)
        valid=covered&~np.ma.getmaskarray(samples)&np.isfinite(raw)
        local_rows=list(range(0,samples.shape[0],level))
        local_cols=list(range(0,samples.shape[1],level))
        if local_rows[-1]!=row_end-row_start:
            local_rows.append(row_end-row_start)
        if local_cols[-1]!=col_end-col_start:
            local_cols.append(col_end-col_start)
        chosen=raw[np.ix_(local_rows,local_cols)]
        chosen_valid=valid[np.ix_(local_rows,local_cols)]
        # Prefix sum gives exact full-resolution NoData checks for every
        # coarse quad, avoiding bridges over unknown pixels between vertices.
        bad=(~valid).astype(np.int32)
        prefix=np.pad(bad,((1,0),(1,0))).cumsum(axis=0).cumsum(axis=1)
        cell_valid=[]
        maximum_error=0.0
        squared_error=0.0
        residual_samples=0
        valid_quad_count=0
        # Measure the actual vertical departure of the full-resolution DEM
        # from the triangulated surface displayed by WebGL.
        # Unknown quads contribute neither faces nor misleading zero errors.
        # Each valid source pixel is counted once in RMSE (the outermost
        # bottom/right boundaries are included at their owning edge cell).
        for r0,r1 in zip(local_rows,local_rows[1:]):
            for c0,c1 in zip(local_cols,local_cols[1:]):
                invalid=int(prefix[r1+1,c1+1]-prefix[r0,c1+1]-
                            prefix[r1+1,c0]+prefix[r0,c0])
                complete=(invalid==0)
                cell_valid.append(complete)
                if not complete:
                    continue
                valid_quad_count+=1
                if level==1:
                    # A native-resolution cell has no interior source
                    # samples; it introduces zero sampling error.
                    residual_samples+=int((r1-r0)*(c1-c0))
                    continue
                weights_r=(np.arange(r0,r1+1,dtype=np.float64)-r0)/(r1-r0)
                weights_c=(np.arange(c0,c1+1,dtype=np.float64)-c0)/(c1-c0)
                # The WebGL index buffer draws triangles (NW,SW,NE)
                # and (NE,SW,SE). Compare to that *piecewise-linear TIN*,
                # not a bilinear surface that the GPU never renders.
                north_west,north_east=raw[r0,c0],raw[r0,c1]
                south_west,south_east=raw[r1,c0],raw[r1,c1]
                u,v=weights_c[None,:],weights_r[:,None]
                upper=north_west+v*(south_west-north_west)+u*(north_east-north_west)
                lower=south_east+(1-u)*(south_west-south_east)+(1-v)*(north_east-south_east)
                interpolated=np.where(u+v<=1,upper,lower)
                residual=raw[r0:r1+1,c0:c1+1]-interpolated
                maximum_error=max(maximum_error,float(np.max(np.abs(residual))))
                # Avoid counting shared seam samples twice in the RMSE.
                block=residual[:r1-r0,:c1-c0]
                squared_error+=float(np.sum(block*block))
                residual_samples+=block.size
                if r1==samples.shape[0]-1:
                    edge=residual[-1,:-1]
                    squared_error+=float(np.dot(edge,edge))
                    residual_samples+=edge.size
                if c1==samples.shape[1]-1:
                    edge=residual[:-1,-1]
                    squared_error+=float(np.dot(edge,edge))
                    residual_samples+=edge.size
                if r1==samples.shape[0]-1 and c1==samples.shape[1]-1:
                    squared_error+=float(residual[-1,-1]**2)
                    residual_samples+=1
        checkpoint(cancel)
        base=src.window_transform(window)
        x0,y0=base*(.5,.5)
        return {
            "source_crs":str(src.crs),"grid_rows":rows,"grid_cols":cols,
            "grid_cell_width_m":float(base.a),"grid_cell_height_m":float(-base.e),
            "grid_origin_xy":[float(x0),float(y0)],
            "level":level,"tile_row":tile_row,"tile_col":tile_col,
            "row_indices":[row_start+r for r in local_rows],
            "col_indices":[col_start+c for c in local_cols],
            "rows":len(local_rows),"cols":len(local_cols),
            "heights":[float(x) if ok else None for x,ok in zip(chosen.flat,chosen_valid.flat)],
            "valid_quads":cell_valid,
            "geometric_error_max_m":maximum_error if valid_quad_count else None,
            "geometric_error_rmse_m":(math.sqrt(squared_error/residual_samples)
                                      if residual_samples else None),
            "geometric_error_samples":residual_samples,
            "valid_quad_count":valid_quad_count,
            "nodata_policy":"unknown_cells_and_intervening_pixels_remove_faces",
            "source_elevation_unit":"m",
        }
