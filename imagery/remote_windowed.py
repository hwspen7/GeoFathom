"""Local file-based, bounded-memory scientific optical processing.

This is a local CLI/library, not a remote path-reading HTTP API.
Window processing preserves the native transform, exact pixel semantics and
NoData. Output is committed atomically only after all windows succeed.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
import rasterio
from rasterio.windows import Window
from analysis.science_raster import require
from .remote_catalog import BY_ID
from .remote_kernels import optical,quality_mask

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def same_grid(a,b):
    return a.crs==b.crs and a.transform==b.transform and a.width==b.width and a.height==b.height

def windows(width,height,tile):
    for row in range(0,height,tile):
        for col in range(0,width,tile):
            yield Window(col,row,min(tile,width-col),min(tile,height-row))

def process(operation,bindings,output,parameters=None,quality=(),tile=512,progress=None):
    method=BY_ID.get(operation)
    require(method is not None and method.group=='Optical' and operation!='ndvi_uncertainty',
            'Windowed processing currently supports the twenty original pointwise optical indices.')
    require(set(bindings)=={r for r,_ in method.roles},'Bind every required role.')
    require(isinstance(tile,int) and 64<=tile<=1024,'Tile size must be 64–1024.')
    params={n:default for n,_,default,lo,hi,integer in method.parameters}
    overrides=parameters or {};require(set(overrides)<=set(params),'Unknown parameter.')
    for n,_,default,lo,hi,integer in method.parameters:
        x=overrides.get(n,default);require(math.isfinite(x) and lo<=x<=hi and (not integer or float(x).is_integer()),'Invalid parameter: '+n)
        params[n]=x
    output=Path(output).resolve();require(not output.exists(),'Output must not already exist.')
    require(output.parent.is_dir(),'Output directory must exist.')
    require(len(quality)<=8,'At most eight global quality masks.')
    tmp=None
    with ExitStack() as ctx:
        bands={};mask_inputs=[];first=None;provenance={}
        def open_band(spec,categorical=False):
            nonlocal first
            path=Path(spec['path']).resolve();require(path!=output,'Input and output paths must differ.')
            ds=ctx.enter_context(rasterio.open(path));b=spec.get('band',1)
            require(ds.driver=='GTiff' and ds.crs and isinstance(b,int) and 1<=b<=ds.count,'Georeferenced GeoTIFF and valid band required.')
            a=ds.transform;require(a.b==0 and a.d==0 and a.a>0 and a.e<0,'Use north-up grids.')
            if first is None:first=ds
            else:require(same_grid(first,ds),'All band grids must match exactly.')
            if categorical:scale,offset=1.,0.
            elif spec.get('encoding','metadata')=='landsat_sr':
                scale,offset=.0000275,-.2
                native=(ds.scales[b-1],ds.offsets[b-1])
                require(native==(1.,0.) or (math.isclose(native[0],scale,rel_tol=1e-7) and math.isclose(native[1],offset,abs_tol=1e-7)),'Raster metadata conflicts with selected Landsat preset.')
            elif spec.get('encoding','metadata')=='custom':scale,offset=float(spec['scale']),float(spec['offset'])
            else:
                require(spec.get('encoding','metadata') in {'metadata','raw'},'Unknown encoding.')
                scale,offset=(ds.scales[b-1],ds.offsets[b-1]) if spec.get('encoding','metadata')=='metadata' else (1.,0.)
            require(math.isfinite(scale) and scale>0 and math.isfinite(offset),'Invalid calibration.')
            return ds,b,scale,offset,spec.get('encoding','metadata'),str(path)
        for role,_ in method.roles:
            item=open_band(bindings[role]);bands[role]=item
            provenance[role]={'path':item[-1],'band':item[1],'scale':item[2],'offset':item[3],'sha256':digest(item[-1])}
        for spec in quality:
            require(spec['scheme'] in {'binary','sentinel_clear','landsat_clear','landsat_unsaturated'},'Unknown quality scheme.')
            item=open_band(spec,True);mask_inputs.append((item,spec['scheme']))
        quality_receipt=[{'path':item[-1],'band':item[1],'scheme':scheme,'sha256':digest(item[-1])} for item,scheme in mask_inputs]
        count=0;total=0.;minimum=np.inf;maximum=-np.inf;tiles=0
        total_tiles=math.ceil(first.width/tile)*math.ceil(first.height/tile)
        try:
            fd,name=tempfile.mkstemp(prefix='.remote-',suffix='.tif',dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver='GTiff',width=first.width,height=first.height,count=1,dtype='float64',crs=first.crs,
                         transform=first.transform,nodata=np.nan,compress='deflate',tiled=True,blockxsize=256,blockysize=256,BIGTIFF='IF_SAFER')
            with rasterio.open(tmp,'w',**profile) as dst:
                dst.update_tags(TERRAIN_UNIT=method.unit,REMOTE_METHOD=operation,PROCESSING='windowed')
                for window in windows(first.width,first.height,tile):
                    v={}
                    for role,(ds,b,scale,offset,encoding,path) in bands.items():
                        z=ds.read(b,window=window,masked=True).astype(float).filled(np.nan)
                        if encoding=='landsat_sr':
                            valid=np.isfinite(z);require(np.all(z[valid]==np.floor(z[valid])) and np.all((z[valid]>=0)&(z[valid]<=65535)),'Landsat preset requires raw DN.')
                            z[z==0]=np.nan
                        z=z*scale+offset;valid=np.isfinite(z)
                        require(not np.isinf(z).any() and np.all((z[valid]>=-.2-1e-9)&(z[valid]<=1.6+1e-9)),'Invalid calibrated reflectance.')
                        v[role]=z
                    common=np.logical_and.reduce([np.isfinite(z) for z in v.values()])
                    for (ds,b,_,_,_,_),scheme in mask_inputs:
                        q=ds.read(b,window=window,masked=True).astype(float).filled(np.nan)
                        common&=quality_mask(q,scheme)==1
                    z=optical(operation,v,params);z[~common]=np.nan
                    require(not np.isinf(z).any(),'Numerical overflow.')
                    good=z[np.isfinite(z)];count+=len(good);tiles+=1
                    if len(good):total+=float(good.sum());minimum=min(minimum,float(good.min()));maximum=max(maximum,float(good.max()))
                    dst.write(z,1,window=window)
                    if progress is not None:progress(tiles/total_tiles)
            require(count>0,'No valid output pixels.')
            receipt={'operation':operation,'parameters':params,'bands':provenance,'quality_masks':quality_receipt,
                     'width':first.width,'height':first.height,'tile_size':tile,'windows':tiles,'valid_cells':count,
                     'nodata_cells':first.width*first.height-count,'minimum':minimum,'maximum':maximum,'mean':total/count,
                     'sha256':digest(tmp),'crs':str(first.crs),'transform':list(first.transform)[:6]}
            # A hard link creates the destination without overwriting an existing
            # file, even if another process created it during the analysis.
            os.link(tmp,output);return receipt
        finally:
            if tmp is not None:tmp.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--tile',type=int,default=512)
    args=parser.parse_args();config=json.loads(args.config.read_text(encoding='utf-8'))
    receipt=process(output=args.output,tile=args.tile,**config)
    print(json.dumps(receipt,indent=2,allow_nan=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
