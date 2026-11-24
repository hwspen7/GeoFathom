"""Bounded native-grid Sentinel-2 L2A crops from approved public STAC assets."""
import base64
import math
import hashlib
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import Window,from_bounds
from rasterio.warp import transform_bounds
from .remote import provider_config,fetch_stac_item,vetted_asset_href
from .remote_calibration import stac_reflectance_calibration,apply_reflectance
from .remote_kernels import quality_mask
from .raster import RasterError

ASSETS={'blue':'blue','green':'green','red':'red','nir':'nir','rededge':'rededge1','rededge2':'rededge2','rededge3':'rededge3','nir_narrow':'nir08','swir1':'swir16','swir2':'swir22','scl':'scl'}

def read_scene(collection,item_id,bbox,roles):
    if collection not in {'sentinel-2-l2a','sentinel-2-c1-l2a'}:raise RasterError('Select a Sentinel-2 L2A public collection.')
    if not 1<=len(roles)<=8 or len(set(roles))!=len(roles) or not set(roles)<=set(ASSETS):raise RasterError('Select one to eight unique supported band roles.')
    west,south,east,north=bbox
    if not all(math.isfinite(x) for x in bbox) or not (-180<=west<east<=180 and -90<=south<north<=90) or max(east-west,north-south)>.2:
        raise RasterError('Use a WGS84 region at most 0.2 degrees per dimension.')
    config=provider_config('earth-search');item=fetch_stac_item(collection,item_id)
    properties=item.get('properties') or {};assets=item['assets'];out=[];size=0
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',GDAL_HTTP_MAX_RETRY='1',GDAL_HTTP_TIMEOUT='20',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.tiff',CPL_VSIL_CURL_CACHE_SIZE='16777216'):
        for role in roles:
            asset=assets.get(ASSETS[role])
            if not isinstance(asset,dict):raise RasterError('Scene lacks required asset: '+role)
            href=vetted_asset_href(asset.get('href'),config['hosts'])
            with rasterio.open('/vsicurl/'+href) as ds:
                if ds.driver!='GTiff' or ds.count!=1 or not ds.crs or ds.transform.b or ds.transform.d or ds.transform.a<=0 or ds.transform.e>=0:raise RasterError('Expected a native north-up single-band COG.')
                bounds=transform_bounds('EPSG:4326',ds.crs,*bbox,densify_pts=21)
                win=from_bounds(*bounds,transform=ds.transform)
                c0=max(0,math.floor(win.col_off));r0=max(0,math.floor(win.row_off))
                c1=min(ds.width,math.ceil(win.col_off+win.width));r1=min(ds.height,math.ceil(win.row_off+win.height))
                w=c1-c0;h=r1-r0
                if not 1<=w<=1024 or not 1<=h<=1024:raise RasterError('Native crop is empty or exceeds 1024 pixels per side; select a smaller region.')
                window=Window(c0,r0,w,h);z=ds.read(1,window=window,masked=True).astype(float).filled(np.nan)
                meta=asset.get('raster:bands',asset.get('bands',[]));band=meta[0] if isinstance(meta,list) and len(meta)==1 and isinstance(meta[0],dict) else {}
                nodata=band.get('nodata',band.get('raster:nodata'))
                if nodata is not None:
                    if not isinstance(nodata,(int,float)) or not math.isfinite(nodata):raise RasterError('Unsupported STAC NoData metadata.')
                    if ds.nodata is not None and ds.nodata!=nodata:raise RasterError('STAC and GeoTIFF NoData disagree.')
                    z[z==nodata]=np.nan
                if role=='scl':
                    quality_mask(z,'sentinel_clear');calibration={'scale':1.,'offset':0.,'source':'raw SCL'};unit='class'
                else:
                    calibration=stac_reflectance_calibration(asset,ds,properties,'earth-search');z=apply_reflectance(z,calibration);unit='reflectance'
                aff=ds.window_transform(window);crs=ds.crs
                with MemoryFile() as mem:
                    with mem.open(driver='GTiff',width=w,height=h,count=1,dtype='float64',crs=crs,transform=aff,nodata=np.nan,compress='deflate') as dst:
                        dst.write(z,1);dst.update_tags(TERRAIN_UNIT=unit,STAC_ITEM=item_id,STAC_ROLE=role)
                    data=mem.read()
                size+=len(data)
                if size>24_000_000:raise RasterError('Combined native crop payload exceeds 24 MB.')
                out.append({'role':role,'name':item_id+'_'+role,'data':base64.b64encode(data).decode(),'unit':unit,
                    'sha256':hashlib.sha256(data).hexdigest(),'asset_href':href,'calibration':calibration,'crs':str(crs),'transform':list(aff)[:6],
                    'shape':[h,w],'native_window':[c0,r0,w,h]})
    return {'collection':collection,'item_id':item_id,'acquired_at':properties.get('datetime'),'bbox':list(bbox),'bands':out,
            'warning':'Native crops retain their original spatial resolution. Explicitly align different grids, including SCL; crops are not an automatic resampling or ground accuracy certification.'}
