"""Public Sentinel-2 integration benchmark and external raster reference comparison.

The published fixture is an independently sourced real scene, not ground truth.
Numerical agreement on that fixture is not atmospheric or field validation.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error
from urllib.parse import quote

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import Window

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
DOI='10.5281/zenodo.21917533'
RECORD='https://zenodo.org/records/21917533/files/'
FILES={'B04.tif':'4c34549d9e0e6703ea5c21744ca63b5a','B08.tif':'66075fa9fb89d0c702da3ce08a701bd4'}

def hash_file(path,algorithm='sha256'):
    h=hashlib.new(algorithm)
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def obtain(root,name,expected):
    root.mkdir(parents=True,exist_ok=True);dest=root/name
    if not dest.exists():
        temp=dest.with_suffix('.part')
        urls=['https://zenodo.org/api/records/21917533/files/'+quote(name,safe='')+'/content',RECORD+quote(name,safe='')+'?download=1']
        errors=[]
        for url in urls:
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'GeoFathom scientific benchmark/1','Accept':'application/octet-stream'})
                with urllib.request.urlopen(req,timeout=60) as response,open(temp,'wb') as out:
                    count=0
                    while chunk:=response.read(1024*1024):
                        count+=len(chunk)
                        if count>16*1024*1024:raise ValueError('Unexpected fixture size.')
                        out.write(chunk)
                if hash_file(temp,'md5')!=expected:raise ValueError('Published fixture checksum mismatch.')
                temp.replace(dest)
                break
            except (urllib.error.URLError,TimeoutError) as error:
                errors.append(type(error).__name__+': '+str(error))
            finally:temp.unlink(missing_ok=True)
        if not dest.exists():raise RuntimeError('Published fixture unavailable: '+'; '.join(errors))
    if hash_file(dest,'md5')!=expected:raise ValueError('Published fixture checksum mismatch.')
    return dest

def compare(candidate,reference,atol,rtol=0,minimum=1):
    if not np.isfinite([atol,rtol]).all() or min(atol,rtol)<0 or minimum<1:raise ValueError('Invalid reference tolerances.')
    n=0;disagreement=0;total=0.;squares=0.;maximum=0.;matches=True
    with rasterio.open(candidate) as a,rasterio.open(reference) as b:
        if (a.crs,a.transform,a.shape)!=(b.crs,b.transform,b.shape):raise ValueError('Reference grids must match exactly.')
        if a.count!=1 or b.count!=1:raise ValueError('Compare explicit single-band outputs.')
        # Fixed-size windows also work when a source has unusually large strips.
        for row in range(0,a.height,512):
            for col in range(0,a.width,512):
                window=Window(col,row,min(512,a.width-col),min(512,a.height-row))
                x=a.read(1,window=window,masked=True).astype(float).filled(np.nan)
                y=b.read(1,window=window,masked=True).astype(float).filled(np.nan)
                if np.isinf(x).any() or np.isinf(y).any():raise ValueError('Infinite reference or candidate values.')
                am=np.isfinite(x);bm=np.isfinite(y);common=am&bm;disagreement+=int(np.count_nonzero(am!=bm))
                x=x[common];y=y[common];d=x-y;n+=len(d)
                if len(d):
                    if not np.isfinite(d).all() or np.max(abs(d))>1e100:raise ValueError('Reference residual exceeds numeric range.')
                    total+=float(d.sum());squares+=float(d@d);maximum=max(maximum,float(np.max(abs(d))))
                    matches=matches and bool(np.allclose(x,y,atol=atol,rtol=rtol))
    if n<minimum:raise ValueError('Insufficient paired cells.')
    return {'passed':bool(disagreement==0 and matches),'paired_cells':n,'mask_disagreement':disagreement,
            'rmse':float(np.sqrt(squares/n)),'bias':total/n,'maximum_absolute_error':maximum,
            'candidate_sha256':hash_file(candidate),'reference_sha256':hash_file(reference),'atol':atol,'rtol':rtol}

def public_scene(root):
    from imagery.remote_routes import RemoteInput,execute
    raw=[obtain(root,n,h) for n,h in FILES.items()]
    with rasterio.open(raw[0]) as a,rasterio.open(raw[1]) as b:
        if (a.crs,a.transform,a.shape)!=(b.crs,b.transform,b.shape):raise ValueError('Published red/NIR grids differ.')
        # Use actual native-grid observations; do not assume undocumented scale or offset.
        w=min(512,a.width);h=min(512,a.height);win=Window((a.width-w)//2,(a.height-h)//2,w,h)
        aff=a.window_transform(win);crs=a.crs
        red=a.read(1,window=win,masked=True).astype(float).filled(np.nan)
        nir=b.read(1,window=win,masked=True).astype(float).filled(np.nan)
        scales=[float(a.scales[0]),float(b.scales[0])];offsets=[float(a.offsets[0]),float(b.offsets[0])]
    def write(path,z,unit):
        with rasterio.open(path,'w',driver='GTiff',width=w,height=h,count=1,dtype='float64',crs=crs,transform=aff,nodata=np.nan) as ds:
            ds.write(z,1);ds.update_tags(TERRAIN_UNIT=unit)
    # Separate independent native-value arithmetic from physical-reflectance claims.
    rs=root/'red_native.tif';ns=root/'nir_native.tif';write(rs,red,'DN');write(ns,nir,'DN')
    inputs=[{'name':x.name,'data':base64.b64encode(x.read_bytes()).decode()} for x in (rs,ns)]
    result=execute(RemoteInput(operation='difference',sources=inputs,bindings={'before':{'source':0,'unit':'DN'},'after':{'source':1,'unit':'DN'}}))
    product=root/'difference_actual.tif';product.write_bytes(base64.b64decode(result['raster']['data']))
    reference=root/'difference_reference.tif';write(reference,nir-red,'DN')
    check=compare(product,reference,0,minimum=100)
    report={'dataset_doi':DOI,'tile':'T33UUP','date':'2023-09-07','published_files':{p.name:hash_file(p) for p in raw},
            'native_scales':scales,'native_offsets':offsets,'window':[int(win.col_off),int(win.row_off),w,h],
            'native_difference':check,'scope':'Real-scene native arithmetic and masks. Not NDVI physical calibration or ground-truth retrieval accuracy.'}
    if not check['passed']:raise ValueError('Real-scene native arithmetic reference failed.')
    return report


def public_oscd_native(root,manifest=None):
    """Author-published, pinned native DN arithmetic without a provider fallback."""
    from scripts.remote_oscd_benchmark import obtain as obtain_oscd,DEFAULT_MANIFEST
    from imagery.remote_routes import RemoteInput,execute
    root=Path(root);manifest=manifest or json.loads(DEFAULT_MANIFEST.read_text());obtain_oscd(root,manifest)
    city=manifest['training_city'];folder=root/'members'/city
    anchor=next((folder/'imgs_1').glob('*_B04.tif'));nir_path=folder/'imgs_1_rect'/'B08.tif'
    with rasterio.open(anchor) as a,rasterio.open(folder/'imgs_1_rect'/'B04.tif') as red_rect,rasterio.open(nir_path) as b:
        if not a.crs or a.shape!=red_rect.shape or b.shape!=a.shape or not np.array_equal(a.read(1),red_rect.read(1)):
            raise ValueError('Cannot establish the published rectified native grid.')
        w=min(512,a.width);h=min(512,a.height);win=Window((a.width-w)//2,(a.height-h)//2,w,h);aff=a.window_transform(win);crs=a.crs
        red=a.read(1,window=win,masked=True).astype(float).filled(np.nan);nir=b.read(1,window=win,masked=True).astype(float).filled(np.nan)
    out=root/'native-arithmetic';out.mkdir(exist_ok=True)
    def write(name,z):
        path=out/name
        with rasterio.open(path,'w',driver='GTiff',width=w,height=h,count=1,dtype='float64',crs=crs,transform=aff,nodata=np.nan) as ds:
            ds.write(z,1);ds.update_tags(TERRAIN_UNIT='DN')
        return path
    inputs=[write('red_native.tif',red),write('nir_native.tif',nir)]
    result=execute(RemoteInput(operation='difference',sources=[{'name':p.name,'data':base64.b64encode(p.read_bytes()).decode()} for p in inputs],
        bindings={'before':{'source':0,'unit':'DN'},'after':{'source':1,'unit':'DN'}}))
    product=out/'difference_actual.tif';product.write_bytes(base64.b64decode(result['raster']['data']));reference=write('difference_reference.tif',nir-red)
    check=compare(product,reference,0,minimum=100)
    if not check['passed']:raise ValueError('Published OSCD native arithmetic reference failed.')
    return {'passed':True,'dataset':manifest['dataset'],'source':manifest['source'],'city':city,
        'published_files':{anchor.name:hash_file(anchor),'rectified_B08.tif':hash_file(nir_path)},
        'window':[int(win.col_off),int(win.row_off),w,h],'native_difference':check,
        'scope':'Pinned author-sourced real-scene native DN arithmetic and masks; no surface-reflectance or field accuracy claim.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--public-scene',type=Path);parser.add_argument('--oscd-native',type=Path);parser.add_argument('--candidate',type=Path);parser.add_argument('--reference',type=Path)
    parser.add_argument('--atol',type=float,default=0);parser.add_argument('--rtol',type=float,default=0);parser.add_argument('--minimum',type=int,default=1);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if not np.isfinite([args.atol,args.rtol]).all() or min(args.atol,args.rtol)<0 or args.minimum<1:parser.error('Invalid tolerance or sample minimum.')
    try:
        if args.oscd_native is not None:result=public_oscd_native(args.oscd_native)
        elif args.public_scene is not None:result=public_scene(args.public_scene)
        elif args.candidate is not None and args.reference is not None:result=compare(args.candidate,args.reference,args.atol,args.rtol,args.minimum)
        else:parser.error('Specify OSCD native, published scene, or candidate and reference.')
    except Exception as error:
        result={'passed':False,'dataset_doi':DOI if args.public_scene is not None else None,'error_type':type(error).__name__,'error':str(error),'scope':'Validation did not complete; no scientific accuracy claim.'}
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2),file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,indent=2));return 0 if result.get('passed',True) else 1
if __name__=='__main__':raise SystemExit(main())
