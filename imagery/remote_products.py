"""Native-grid multiband scientific exports with separate bounded display previews."""
import base64
import hashlib
import io
import numpy as np
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import array_bounds,from_bounds
from rasterio.warp import calculate_default_transform,reproject,Resampling
from pyproj import Transformer
from pyproj.exceptions import ProjError
from analysis.science_raster import require


def rgb_product(kind,stack,grid,roles):
    valid=np.isfinite(stack).all(axis=0)
    require(valid.any(),'No common valid RGB observations.')
    require(np.all((stack[:,valid]>=0)&(stack[:,valid]<=1)),'RGB requires calibrated reflectance in [0,1].')
    data=np.where(valid[None,:,:],stack,np.nan)
    h,w=valid.shape
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=w,height=h,count=3,dtype='float64',
                      crs=grid.crs,transform=grid.transform,nodata=np.nan,compress='deflate') as ds:
            ds.write(data)
            for i,role in enumerate(roles,1):
                ds.set_band_description(i,role);ds.update_tags(i,TERRAIN_UNIT='reflectance',SPECTRAL_ROLE=role)
            ds.update_tags(TERRAIN_UNIT='reflectance',REMOTE_METHOD=kind,DISPLAY_CHANNEL_ORDER=','.join(roles))
        raw=mem.read()
    require(len(raw)<=24_000_000,'RGB scientific product exceeds export budget.')
    channels=data[:,valid]
    summary={'valid_cells':int(valid.sum()),'nodata_cells':int(valid.size-valid.sum()),
             'minimum':float(channels.min()),'maximum':float(channels.max()),
             'channels':[{'role':role,'minimum':float(channels[i].min()),'maximum':float(channels[i].max())} for i,role in enumerate(roles)]}
    product={'name':kind,'data':base64.b64encode(raw).decode(),'unit':'reflectance','band':1,'band_count':3,
             'sha256':hashlib.sha256(raw).hexdigest(),'summary':summary}
    return product,rgb_preview(data,grid)


def rgb_preview(data,grid):
    try:
        h,w=data.shape[1:];aff,ww,hh=calculate_default_transform(grid.crs,'EPSG:3857',w,h,*array_bounds(h,w,grid.transform))
        if min(ww,hh)<=0:return None
        west,south,east,north=array_bounds(hh,ww,aff)
        reverse=Transformer.from_crs(3857,4326,always_xy=True)
        lon0,lat0=reverse.transform(west,south);lon1,lat1=reverse.transform(east,north)
        if not(-180<=lon0<lon1<=180 and lon1-lon0<170 and -85.0512<=lat0<lat1<=85.0512):return None
        scale=min(1,640/max(ww,hh));ww=max(1,round(ww*scale));hh=max(1,round(hh*scale))
        target=from_bounds(west,south,east,north,ww,hh);out=np.full((3,hh,ww),np.nan)
        for i in range(3):
            reproject(data[i],out[i],src_transform=grid.transform,src_crs=grid.crs,src_nodata=np.nan,
                      dst_transform=target,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.nearest)
        valid=np.isfinite(out).all(axis=0)
        if not valid.any():return None
        rgba=np.zeros((hh,ww,4),np.uint8)
        rgba[valid,:3]=np.rint(out[:,valid].T*255).astype(np.uint8);rgba[valid,3]=255
        f=io.BytesIO();Image.fromarray(rgba).save(f,format='PNG')
        return {'png':'data:image/png;base64,'+base64.b64encode(f.getvalue()).decode(),
                'corners':[[lon0,lat1],[lon1,lat1],[lon1,lat0],[lon0,lat0]],
                'width':ww,'height':hh,'valid_cells':int(valid.sum()),'minimum':float(out[:,valid].min()),
                'maximum':float(out[:,valid].max()),'unit':'reflectance',
                'method':'RGB display only; nearest projected preview, original three scientific bands unchanged.'}
    except (ValueError,RuntimeError,OSError,ProjError):return None
