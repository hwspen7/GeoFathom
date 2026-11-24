"""Disk-backed dated multiband GeoTIFF executor with a shared global kriging fit.

Explicitly prealigned and quality-masked input; no spatial resampling.
"""
import argparse,hashlib,json,os,tempfile
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
from pyproj import CRS
from .science_raster import require
from .spacetime_kriging import fit
from .spacetime_models import trend,temporal

METHODS=('coverage','sen','exceedance','st_universal_mean','st_universal_sd')
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as s:
        for buf in iter(lambda:s.read(1024*1024),b''):h.update(buf)
    return h.hexdigest()

def execute(source,output,times,method,parameters,tile=64,time_unit='day'):
    require(method in METHODS,'Unsupported disk method; global inference must not be tiled independently.')
    require(isinstance(tile,int) and 16<=tile<=128,'Tile size must be 16–128.')
    src=Path(source).resolve(strict=True);dst=Path(output).absolute()
    require(src!=dst.resolve() and not dst.exists(),'Output must be a new file.')
    require(dst.parent.is_dir(),'Output parent must exist.')
    t=np.asarray(times,float);n=len(t)
    require(6<=n<=64 and np.isfinite(t).all() and np.all(np.diff(t)>=1e-9) and t[-1]-t[0]<=1e9,'Invalid dated time axis.')
    require(isinstance(time_unit,str) and 0<len(time_unit)<=24,'Invalid time unit.')
    p=dict(parameters);global_fit=method.startswith('st_universal_')
    if global_fit:
        defaults={'spatial_range':100.,'temporal_range':30.,'nugget_ratio':.1,'interaction':.5,'sample_limit':128,'seed':42,'fit_covariance':0,'horizon':30.}
        limits={'spatial_range':(1e-6,1e8),'temporal_range':(1e-6,1e8),'nugget_ratio':(1e-6,10),'interaction':(.05,1),'sample_limit':(12,256),'seed':(0,2147483647),'fit_covariance':(0,1),'horizon':(1e-6,1e7)}
    elif method=='exceedance':
        defaults={'threshold':0.,'minimum_observations':6};limits={'threshold':(-1e50,1e50),'minimum_observations':(3,n)}
    else:defaults={};limits={}
    require(set(p)<=set(defaults),'Unexpected disk method parameters.')
    p={**defaults,**p}
    for key,(lo,hi) in limits.items():
        x=p[key];require(isinstance(x,(int,float)) and np.isfinite(x) and lo<=x<=hi,'Invalid parameter '+key)
        if key in ('sample_limit','seed','fit_covariance','minimum_observations'):
            require(x==int(x),'Integer parameter required');p[key]=int(x)
    before=sha(src);temp=None;meta={};valid_count=0;low=np.inf;high=-np.inf
    try:
        with rasterio.open(src) as ds:
            require(ds.driver=='GTiff' and ds.crs and ds.count==n,'Use a georeferenced dated multiband GeoTIFF.')
            require(ds.transform.b==ds.transform.d==0 and ds.transform.a>0 and ds.transform.e<0,'North-up grid required.')
            require(ds.width*ds.height<=25_000_000 and ds.width*ds.height*n<=250_000_000,'Disk cube exceeds work budget.')
            if global_fit:
                crs=CRS.from_user_input(ds.crs)
                require(crs.is_projected and all(abs(a.unit_conversion_factor-1)<1e-9 for a in crs.axis_info[:2]),'Global kriging requires projected metre coordinates.')
                require(ds.width*ds.height*p['sample_limit']**2<=300_000_000,'Global prediction work budget exceeded.')
            scales=np.asarray(ds.scales,float);offsets=np.asarray(ds.offsets,float)
            require(np.isfinite(scales).all() and np.all(scales>0) and np.isfinite(offsets).all(),'Invalid band calibration.')
            unit=ds.tags().get('TERRAIN_UNIT','unspecified')
            require(all(u in (None,'',unit) for u in ds.units),'Band units disagree with dataset unit.')
            def windows():
                for y in range(0,ds.height,tile):
                    for x in range(0,ds.width,tile):yield Window(x,y,min(tile,ds.width-x),min(tile,ds.height-y))
            def read(win):
                z=ds.read(window=win,masked=True).astype(float).filled(np.nan)*scales[:,None,None]+offsets[:,None,None]
                require(not np.isinf(z).any() and (not np.isfinite(z).any() or np.max(abs(z[np.isfinite(z)]))<=1e50),'Invalid calibrated values.')
                return z
            if global_fit:
                rng=np.random.default_rng(p['seed']);keys=np.empty(0);coords=np.empty((0,3));vals=np.empty(0);limit=p['sample_limit']
                for win in windows():
                    z=read(win);ids=np.argwhere(np.isfinite(z))
                    if not len(ids):continue
                    # Independent continuous random priorities; retain globally
                    # smallest keys, equivalent to uniform sampling without replacement.
                    priority=rng.random(len(ids));keys=np.r_[keys,priority]
                    i,r,c=ids.T
                    x=np.column_stack(((c+win.col_off+.5)*ds.transform.a,(r+win.row_off+.5)*abs(ds.transform.e),t[i]-t[0]))
                    coords=np.vstack((coords,x));vals=np.r_[vals,z[tuple(ids.T)]]
                    if len(keys)>limit:
                        keep=np.argpartition(keys,limit-1)[:limit];keys=keys[keep];coords=coords[keep];vals=vals[keep]
                require(len(vals)>=12,'Insufficient global valid observations.')
                order=np.argsort(keys);coords=coords[order];vals=vals[order]
                predict,meta=fit(coords,vals,{**p,'universal':1})
                meta['global_training_coordinates']=coords.tolist()
                meta['sampling']='Uniform global random priorities, deterministic for source, seed and tile size; one fit for all output windows.'
            fd,temp=tempfile.mkstemp(prefix='.spacetime-',suffix='.tif',dir=dst.parent);os.close(fd)
            profile=dict(driver='GTiff',width=ds.width,height=ds.height,count=1,dtype='float64',crs=ds.crs,transform=ds.transform,nodata=np.nan,tiled=True,blockxsize=128,blockysize=128,compress='deflate')
            output_unit='fraction' if method in ('coverage','exceedance') else unit+'/'+time_unit if method=='sen' else unit
            with rasterio.open(temp,'w',**profile) as out:
                for win in windows():
                    if global_fit:
                        r,c=np.indices((int(win.height),int(win.width)))
                        xyz=np.column_stack(((c.ravel()+win.col_off+.5)*ds.transform.a,(r.ravel()+win.row_off+.5)*abs(ds.transform.e),np.full(r.size,t[-1]-t[0]+p['horizon'])))
                        mean,sd=predict(xyz);z=(mean if method.endswith('_mean') else sd).reshape(r.shape)
                    elif method=='sen':z,_=trend(read(win),t,'sen')
                    else:z,_=temporal(read(win),t,method,p)
                    mask=np.isfinite(z);valid_count+=int(mask.sum())
                    if mask.any():low=min(low,float(z[mask].min()));high=max(high,float(z[mask].max()))
                    out.write(z,1,window=win)
                out.update_tags(TERRAIN_UNIT=output_unit,SOURCE_SHA256=before,METHOD=method)
            require(valid_count>0,'No valid output cells.')
        require(sha(src)==before,'Source changed during calculation.')
        output_sha=sha(temp)
        # Atomic no-overwrite publication on the same filesystem.
        os.link(temp,dst)
        return {'method':method,'source_sha256':before,'output_sha256':output_sha,'times':t.tolist(),'time_unit':time_unit,'unit':output_unit,'tile':tile,'valid_cells':valid_count,'minimum':low,'maximum':high,'parameters':p,'metrics':meta,'quality_policy':'Input must already be quality-masked; native NoData honored.'}
    finally:
        if temp is not None:Path(temp).unlink(missing_ok=True)

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('source');a.add_argument('output');a.add_argument('--times-json',required=True);a.add_argument('--method',required=True,choices=METHODS);a.add_argument('--parameters-json',default='{}');a.add_argument('--tile',type=int,default=64);a.add_argument('--time-unit',default='day')
    x=a.parse_args();print(json.dumps(execute(x.source,x.output,json.loads(x.times_json),x.method,json.loads(x.parameters_json),x.tile,x.time_unit),allow_nan=False))
if __name__=='__main__':main()
