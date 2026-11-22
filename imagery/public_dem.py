"""Bounded, fixed-provider Copernicus DSM acquisition. No arbitrary remote URLs.

Source: https://registry.opendata.aws/copernicus-dem/
Original public 2021 release: meter elevations on a geographic grid.
The output is an explicitly resampled local UTM subset, with nodata preserved.
"""
import math
import tempfile
from pathlib import Path
from datetime import date
from threading import BoundedSemaphore

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds, reproject, Resampling
from .raster import RasterError
from .store import imagery_dir, store_upload

_FETCH_SLOT=BoundedSemaphore(1)
_NODATA=-9999.0

def tile_url(lat,lon,resolution):
    if resolution not in (30,90):
        raise RasterError("Choose GLO-30 or GLO-90.")
    arc=10 if resolution==30 else 30
    name=f"Copernicus_DSM_COG_{arc}_{'N' if lat>=0 else 'S'}{abs(lat):02d}_00_{'E' if lon>=0 else 'W'}{abs(lon):03d}_00_DEM"
    return f"https://copernicus-dem-{resolution}m.s3.amazonaws.com/{name}/{name}.tif"

def _grid(bbox,resolution):
    if resolution not in (30,90) or len(bbox)!=4 or not all(math.isfinite(v) for v in bbox):
        raise RasterError("Invalid DEM area or resolution.")
    w,s,e,n=bbox
    if not (-180<=w<e<=180 and -79<=s<n<=83):
        raise RasterError("Select a local non-polar area; antimeridian regions are not supported.")
    if e-w>.25 or n-s>.25:
        raise RasterError("Zoom in or select a smaller area before fetching elevation.")
    lon=(w+e)/2;lat=(s+n)/2
    zone=min(60,max(1,math.floor((lon+180)/6)+1))
    crs=f"EPSG:{(32600 if lat>=0 else 32700)+zone}"
    x0,y0,x1,y1=transform_bounds("EPSG:4326",crs,w,s,e,n,densify_pts=21)
    # Add a few cells so slope neighborhoods and boundary clipping have context.
    x0=math.floor(x0/resolution)*resolution-2*resolution
    y1=math.ceil(y1/resolution)*resolution+2*resolution
    width=max(5,math.ceil((x1-x0)/resolution)+2)
    height=max(5,math.ceil((y1-y0)/resolution)+2)
    if max(width,height)>256:
        raise RasterError("Area exceeds 256 DEM cells per side. Select a smaller area (about 7 km at 30 m, 22 km at 90 m).")
    return crs,from_origin(x0,y1,resolution,resolution),width,height

def _tile_indices(bounds):
    w,s,e,n=bounds
    tiles=[(y,x) for y in range(math.floor(s),math.ceil(n))
                    for x in range(math.floor(w),math.ceil(e))]
    if len(tiles)>4:raise RasterError("DEM area spans too many source tiles.")
    return tiles

def _read_tiles(bbox,resolution):
    crs,affine,width,height=_grid(bbox,resolution)
    expanded=transform_bounds(crs,"EPSG:4326",*rasterio.transform.array_bounds(height,width,affine),densify_pts=21)
    destination=np.full((height,width),_NODATA,dtype=np.float32)
    unavailable=[]
    # Fixed trusted public bucket; bounded range reads and one concurrent job.
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",GDAL_HTTP_TIMEOUT="15",
                      GDAL_HTTP_CONNECTTIMEOUT="5",GDAL_HTTP_MAX_RETRY="0",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        for y,x in _tile_indices(expanded):
            url=tile_url(y,x,resolution)
            try:
                with rasterio.open(url) as source:
                    if source.count!=1 or source.crs is None:
                        raise RasterError("Unexpected Copernicus DEM tile format.")
                    part=np.full_like(destination,_NODATA)
                    reproject(source=rasterio.band(source,1),destination=part,
                              dst_transform=affine,dst_crs=crs,dst_nodata=_NODATA,
                              resampling=Resampling.bilinear,num_threads=1,warp_mem_limit=32)
                    valid=np.isfinite(part)&(part!=_NODATA)
                    destination[valid]=part[valid]
            except rasterio.errors.RasterioIOError:
                unavailable.append(f"{y},{x}")
    valid=np.isfinite(destination)&(destination!=_NODATA)
    if not valid.any():
        raise RasterError("No public DEM data returned. Check network/coverage or try GLO-90. No elevations were fabricated.")
    return destination,crs,affine,int(valid.sum()),unavailable

def fetch_dem_subset(bbox,resolution):
    _grid(bbox,resolution)
    if not _FETCH_SLOT.acquire(blocking=False):
        raise RasterError("Another elevation download is active.")
    temporary=None
    try:
        array,crs,affine,count,missing=_read_tiles(bbox,resolution)
        root=imagery_dir();root.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".dem-",suffix=".tif",dir=root,delete=False) as f:
            temporary=Path(f.name)
        # Source attribution is persisted; missing data is not assumed to be zero.
        provenance=(f"Copernicus DEM GLO-{resolution} Public 2021 DSM, accessed {date.today().isoformat()} "
                    f"from registry.opendata.aws/copernicus-dem; local UTM {resolution} m bilinear resampling. "
                    "Contains modified Copernicus DEM data; buildings and vegetation are included.")
        with rasterio.open(temporary,"w",driver="GTiff",height=array.shape[0],width=array.shape[1],
            count=1,dtype="float32",crs=crs,transform=affine,nodata=_NODATA,compress="deflate") as output:
            output.write(array,1)
            output.update_tags(SOURCE=provenance,VERTICAL_UNIT="meter")
        asset=store_upload(temporary,f"Copernicus GLO-{resolution} {bbox[0]:.4f},{bbox[1]:.4f}.tif",provenance)
        return {"asset":asset,"resolution_m":resolution,"valid_cells":count,"total_cells":int(array.size),
                "missing_tiles":missing,"warning":"DSM, not bare-earth DTM. Source coverage and elevation accuracy vary; not survey-grade."}
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
        _FETCH_SLOT.release()
