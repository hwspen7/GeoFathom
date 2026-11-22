"""Bounded local DEM mosaic, clip and resampling operations.

The first source supplies the projected target CRS. Operations preserve NoData
and never assert that resampling improves native spatial or vertical accuracy.
"""
from contextlib import ExitStack
from math import ceil, floor, isfinite
from pathlib import Path
from threading import BoundedSemaphore
import tempfile

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.windows import Window, transform as window_transform
from rasterio.warp import reproject, transform_bounds, transform_geom, Resampling

from geometry.measure import measure_geometry
from imagery.raster import RasterError
from imagery.store import imagery_dir, store_upload
from terrain.engine import _check_dem
from terrain.cancellation import checkpoint
from terrain.vertical import vertical_datum, check_vertical_compatibility

_PREPARE_SLOT=BoundedSemaphore(1)
# The output is written in 512 x 512 windows. A conservative on-disk grid
# ceiling protects compute time and catalog size, not working-set RAM.
_MAX_PIXELS=32_000_000
_MAX_SIDE=8192
_BLOCK=512


def prepare_dem(paths, mode, geometry=None, resolution_m=None, sampling='bilinear', cancel=None):
    """Prepare a new GeoTIFF asset from 1–4 trusted local elevation datasets.

    Mosaic uses first-source precedence, filling missing cells from subsequent
    files. Clip uses a WGS84 polygon. Every source is warped to one projected
    meter grid; no arbitrary external raster URLs or native-resolution claims.
    """
    if mode not in {'mosaic', 'clip', 'resample'}:
        raise RasterError('Choose mosaic, clip, or resample.')
    if not 1 <= len(paths) <= 4 or (mode=='mosaic' and len(paths)<2) or (mode!='mosaic' and len(paths)!=1):
        raise RasterError('Mosaic needs 2–4 DEMs; clip and resample need exactly one.')
    if sampling not in {'nearest','bilinear'}:
        raise RasterError('Resampling must be nearest or bilinear.')
    if resolution_m is not None and (not isfinite(resolution_m) or not 1 <= resolution_m <= 1000):
        raise RasterError('Output grid resolution must be 1–1,000 meters.')
    if mode=='clip':
        if not isinstance(geometry,dict) or geometry.get('type') not in ('Polygon','MultiPolygon'):
            raise RasterError('Clipping requires an explicit polygon selection.')
        measure_geometry(geometry)
    elif geometry is not None:
        raise RasterError('Only Clip uses a study-area polygon.')
    if not _PREPARE_SLOT.acquire(blocking=False):
        raise RasterError('Another DEM preparation is active.')
    temporary=None
    try:
        with ExitStack() as stack:
            sources=[stack.enter_context(rasterio.open(path)) for path in paths]
            for src in sources:
                _check_dem(src)
            datums=[vertical_datum(src) for src in sources]
            datum=check_vertical_compatibility(datums)
            all_datums_known=all(label is not None for label in datums)
            crs=sources[0].crs
            res=float(resolution_m if resolution_m is not None else min(abs(sources[0].transform.a),abs(sources[0].transform.e)))
            if not isfinite(res) or not 1 <= res <= 1000:
                raise RasterError('Source grid has unsupported output resolution; choose 1–1,000 m.')
            bounds=[transform_bounds(src.crs,crs,*src.bounds,densify_pts=21) for src in sources]
            west=min(b[0] for b in bounds);south=min(b[1] for b in bounds)
            east=max(b[2] for b in bounds);north=max(b[3] for b in bounds)
            projected_geometry=None
            if mode=='clip':
                projected_geometry=transform_geom('EPSG:4326',crs,geometry)
                from shapely.geometry import shape
                clip_bounds=shape(projected_geometry).bounds
                west=max(west,clip_bounds[0]);south=max(south,clip_bounds[1])
                east=min(east,clip_bounds[2]);north=min(north,clip_bounds[3])
            if not (east>west and north>south):
                raise RasterError('Selected region does not overlap the source DEM.')
            # Register the output grid to the first DEM's pixel origin,
            # not an arbitrary global multiple of the output resolution.
            # Otherwise even same-resolution operations shift cell centres
            # and unnecessarily interpolate every source elevation.
            anchor_x=float(sources[0].transform.c)
            anchor_y=float(sources[0].transform.f)
            c0=floor((west-anchor_x)/res)
            c1=ceil((east-anchor_x)/res)
            r0=floor((anchor_y-north)/res)
            r1=ceil((anchor_y-south)/res)
            x0=anchor_x+c0*res
            y1=anchor_y-r0*res
            width=int(c1-c0);height=int(r1-r0)
            if width<1 or height<1 or width>_MAX_SIDE or height>_MAX_SIDE or width*height>_MAX_PIXELS:
                raise RasterError('DEM processing exceeds 32 million pixels or 8192 per side; choose a coarser output grid.')
            affine=from_origin(x0,y1,res,res)
            method=Resampling.nearest if sampling=='nearest' else Resampling.bilinear
            checkpoint(cancel)
            root=imagery_dir();root.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix='.dem-work-',suffix='.tif',dir=root,delete=False) as handle:
                temporary=Path(handle.name)
            provenance=(f'GeoFathom DEM {mode}; {len(paths)} local input(s); first-source overlap precedence; '
                        f'projected meter grid {res:g} m; {sampling} resampling. '
                        'NoData preserved. Input native resolution, epochs and vertical datums must be independently verified.')
            count=0
            # Keep raster reprojection, polygon clipping and nodata merging in
            # one bounded window. Both small and large DEMs share this path.
            # The first source wins where multiple datasets overlap.
            with rasterio.open(temporary,'w',driver='GTiff',width=width,height=height,count=1,
                               dtype='float32',crs=crs,transform=affine,nodata=np.nan,
                               tiled=True,blockxsize=256,blockysize=256,
                               compress='deflate') as target:
                for top in range(0,height,_BLOCK):
                    for left in range(0,width,_BLOCK):
                        checkpoint(cancel)
                        h=min(_BLOCK,height-top);w=min(_BLOCK,width-left)
                        window=Window(left,top,w,h)
                        local_transform=window_transform(window,affine)
                        merged=np.full((h,w),np.nan,dtype=np.float32)
                        for source in sources:
                            checkpoint(cancel)
                            part=np.full((h,w),np.nan,dtype=np.float32)
                            reproject(source=rasterio.band(source,1),destination=part,
                                      src_nodata=source.nodata,dst_nodata=np.nan,
                                      dst_transform=local_transform,dst_crs=crs,
                                      resampling=method,num_threads=1,warp_mem_limit=32,
                                      init_dest_nodata=True)
                            fresh=np.isfinite(part)&~np.isfinite(merged)
                            merged[fresh]=part[fresh]
                        if projected_geometry is not None:
                            inside=geometry_mask([projected_geometry],out_shape=merged.shape,
                                                 transform=local_transform,invert=True)
                            merged[~inside]=np.nan
                        count+=int(np.count_nonzero(np.isfinite(merged)))
                        target.write(merged,1,window=window)
                output_tags={'SOURCE':provenance,'VERTICAL_UNIT':'meter'}
                # An unknown contributor must not silently inherit a known
                # vertical reference from another source in the mosaic.
                if datum is not None and all_datums_known:
                    output_tags['VERTICAL_DATUM']=datum
                target.update_tags(**output_tags)
            if not count:
                raise RasterError('DEM operation produced no valid source elevations.')
            checkpoint(cancel)
            asset=store_upload(temporary,f'Terrain {mode} {res:g} m.tif',provenance)
            quality=('Vertical datum labels match but are not independently verified. '
                     if all_datums_known else
                     'One or more source vertical datum labels are missing; vertical compatibility is unverified. ')
            return {'asset':asset,'operation':mode,'valid_cells':count,'total_cells':int(width*height),
                    'resolution_m':res,'warning':quality+'Output grid resolution is not a certificate of native source elevation accuracy or vertical-datum correctness.'}
    except rasterio.errors.RasterioError as error:
        raise RasterError('DEM preparation failed to read or transform the input GeoTIFF.') from error
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
        _PREPARE_SLOT.release()
