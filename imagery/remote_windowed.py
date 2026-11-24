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
from .remote_catalog import BY_ID,WINDOWED_IDS,WINDOWED_HALO
from .remote_kernels import quality_mask
from .remote_band import read_calibrated
from .remote_tile_kernels import compute
from types import SimpleNamespace

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
    require(operation in WINDOWED_IDS,'Operation is not certified for finite-neighborhood disk processing.')
    require(set(bindings)=={r for r,_ in method.roles},'Bind every required role.')
    require(isinstance(tile,int) and 64<=tile<=1024,'Tile size must be 64–1024.')
    params={n:default for n,_,default,lo,hi,integer in method.parameters}
    overrides=parameters or {};require(set(overrides)<=set(params),'Unknown parameter.')
    for n,_,default,lo,hi,integer in method.parameters:
        x=overrides.get(n,default);require(math.isfinite(x) and lo<=x<=hi and (not integer or float(x).is_integer()),'Invalid parameter: '+n)
        params[n]=int(x) if integer else float(x)
    output=Path(output).resolve();require(not output.exists(),'Output must not already exist.')
    require(output.parent.is_dir(),'Output directory must exist.')
    require(len(quality)<=8,'At most eight global quality masks.')
    tmp=None
    with ExitStack() as ctx:
        bands={};mask_inputs=[];first=None;provenance={}
        def open_band(spec,quantity):
            nonlocal first
            path=Path(spec['path']).resolve();require(path!=output,'Input and output paths must differ.')
            ds=ctx.enter_context(rasterio.open(path));b=spec.get('band',1)
            require(ds.driver=='GTiff' and ds.crs and isinstance(b,int) and 1<=b<=ds.count,'Georeferenced GeoTIFF and valid band required.')
            a=ds.transform;require(a.b==0 and a.d==0 and a.a>0 and a.e<0,'Use north-up grids.')
            if first is None:first=ds
            else:require(same_grid(first,ds),'All band grids must match exactly.')
            encoding=spec.get('encoding','metadata')
            require(encoding in {'metadata','raw','landsat_sr','landsat_st','custom'},'Unknown encoding.')
            binding=SimpleNamespace(band=b,encoding=encoding,scale=float(spec.get('scale',1)),offset=float(spec.get('offset',0)),unit=spec.get('unit',''))
            require(math.isfinite(binding.scale) and binding.scale>0 and math.isfinite(binding.offset),'Invalid calibration.')
            # Validate metadata using one native pixel, before opening output.
            _,unit,scale,offset=read_calibrated(ds,binding,quantity,Window(0,0,1,1))
            return ds,binding,quantity,unit,scale,offset,str(path)
        for role,quantity in method.roles:
            item=open_band(bindings[role],quantity);bands[role]=item
            provenance[role]={'path':item[-1],'band':item[1].band,'quantity':quantity,'unit':item[3],'scale':item[4],'offset':item[5],'sha256':digest(item[-1])}
        numeric_units={item[3] for item in bands.values() if item[2]=='numeric'}
        require(len(numeric_units)<=1,'Comparable numerical bands must share physical units.')
        unit=next(iter(bands.values()))[3] if method.unit=='source' else method.unit
        for spec in quality:
            require(spec['scheme'] in {'binary','sentinel_clear','landsat_clear','landsat_unsaturated'},'Unknown quality scheme.')
            roles=spec.get('roles',[]) or list(bindings)
            require(set(roles)<=set(bindings),'Unknown quality mask target role.')
            item=open_band({**spec,'encoding':'raw'},'class');mask_inputs.append((item,spec['scheme'],roles))
        quality_receipt=[{'path':item[-1],'band':item[1].band,'scheme':scheme,'roles':roles,'sha256':digest(item[-1])} for item,scheme,roles in mask_inputs]
        halo=params['radius'] if operation in WINDOWED_HALO else 0
        count=0;total=0.;minimum=np.inf;maximum=-np.inf;tiles=0
        total_tiles=math.ceil(first.width/tile)*math.ceil(first.height/tile)
        try:
            fd,name=tempfile.mkstemp(prefix='.remote-',suffix='.tif',dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver='GTiff',width=first.width,height=first.height,count=1,dtype='float64',crs=first.crs,
                         transform=first.transform,nodata=np.nan,compress='deflate',tiled=True,blockxsize=256,blockysize=256,BIGTIFF='IF_SAFER')
            with rasterio.open(tmp,'w',**profile) as dst:
                dst.update_tags(TERRAIN_UNIT=unit,REMOTE_METHOD=operation,PROCESSING='windowed')
                for window in windows(first.width,first.height,tile):
                    # Read the exact finite support including halo; clip only
                    # at scene boundaries, never at artificial tile boundaries.
                    r0=max(0,int(window.row_off)-halo);c0=max(0,int(window.col_off)-halo)
                    r1=min(first.height,int(window.row_off+window.height)+halo)
                    c1=min(first.width,int(window.col_off+window.width)+halo)
                    expanded=Window(c0,r0,c1-c0,r1-r0)
                    v={role:read_calibrated(ds,binding,quantity,expanded)[0] for role,(ds,binding,quantity,_,_,_,_) in bands.items()}
                    for (ds,binding,quantity,_,_,_,_),scheme,roles in mask_inputs:
                        q=read_calibrated(ds,binding,quantity,expanded)[0]
                        mask=quality_mask(q,scheme)==1
                        for role in roles:v[role][~mask]=np.nan
                    common=np.logical_and.reduce([np.isfinite(z) for z in v.values()])
                    z=compute(operation,v,params);z[~common]=np.nan
                    dr=int(window.row_off)-r0;dc=int(window.col_off)-c0
                    z=z[dr:dr+int(window.height),dc:dc+int(window.width)]
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
                     'width':first.width,'height':first.height,'tile_size':tile,'halo_cells':halo,'unit':unit,'windows':tiles,'valid_cells':count,
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
