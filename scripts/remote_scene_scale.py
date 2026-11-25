"""Deterministic scene-scale window/memory verification with independent arithmetic."""
import argparse
import json
from pathlib import Path
import sys
from threading import Event,Thread
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import psutil
import rasterio
from rasterio.transform import from_origin
from imagery.remote_windowed import process,windows,digest
from analysis.science_raster import require


def fixture(window):
    r,c=np.indices((int(window.height),int(window.width)));r+=int(window.row_off);c+=int(window.col_off)
    red=.1+((r+c)%1000)*.0001;nir=.4+((r+2*c)%1000)*.0001;clear=(r*17+c*7)%31>2
    return red,nir,clear


def run(root,side=4096,tiles=(128,512),maximum_rss_mb=1024):
    require(type(side) is int and 64<=side<=8192,'Use a 64–8192 scene side.')
    root=Path(root);root.mkdir(parents=True,exist_ok=True);paths={r:root/(r+'.tif') for r in ('red','nir','qa')}
    from contextlib import ExitStack
    with rasterio.Env(GDAL_CACHEMAX=32*1024**2),ExitStack() as stack:
        outputs={r:stack.enter_context(rasterio.open(path,'w',driver='GTiff',width=side,height=side,count=1,dtype='float64',crs='EPSG:32617',transform=from_origin(300000,4450000,10,10),nodata=np.nan,compress='deflate',tiled=True,blockxsize=256,blockysize=256)) for r,path in paths.items()}
        for w in windows(side,side,256):
            red,nir,qa=fixture(w);red[~qa]=20000.;nir[~qa]=20000.
            for r,z in [('red',red),('nir',nir),('qa',qa.astype(float))]:outputs[r].write(z,1,window=w)
        for r,ds in outputs.items():ds.update_tags(TERRAIN_UNIT='class' if r=='qa' else 'reflectance')
    checks=[]
    for tile in tiles:
        output=root/('ndvi-'+str(tile)+'.tif');require(not output.exists(),'Choose a new scene-scale work directory.')
        stop=Event();rss=[psutil.Process().memory_info().rss]
        def sample():
            p=psutil.Process()
            while not stop.wait(.02):rss.append(p.memory_info().rss)
        watcher=Thread(target=sample,daemon=True);watcher.start();start=time.perf_counter()
        try:
            with rasterio.Env(GDAL_CACHEMAX=32*1024**2):receipt=process('ndvi',{r:{'path':str(paths[r]),'encoding':'raw'} for r in ('red','nir')},output,
                quality=[{'path':str(paths['qa']),'scheme':'binary'}],tile=tile)
        finally:elapsed=time.perf_counter()-start;stop.set();watcher.join()
        paired=0;maximum=0.;mismatch=0
        with rasterio.open(output) as ds:
            for w in windows(side,side,256):
                red,nir,valid=fixture(w);expected=np.where(valid,(nir-red)/(nir+red),np.nan);actual=ds.read(1,window=w)
                mismatch+=int(np.count_nonzero(np.isfinite(actual)!=valid));paired+=int(valid.sum())
                maximum=max(maximum,float(np.max(np.abs(actual[valid]-expected[valid]))))
        peak=max(rss)/1024**2
        require(mismatch==0 and maximum<=1e-14 and peak<=maximum_rss_mb,'Scene-scale arithmetic, mask or RSS bound failed.')
        checks.append({'tile':tile,'elapsed_seconds':elapsed,'pixels_per_second':side*side/elapsed,'peak_rss_mb':peak,
            'maximum_rss_mb':maximum_rss_mb,'paired_cells':paired,'mask_disagreement':mismatch,'maximum_absolute_error':maximum,'output_sha256':digest(output)})
    from jobs.reproducibility import software_record
    return {'passed':True,'benchmark_sha256':digest(__file__),'software':software_record(),'shape':[side,side],'cells':side*side,'checks':checks,'input_sha256':{r:digest(p) for r,p in paths.items()},
        'scope':'Structured synthetic scene-scale QA/window arithmetic and observed CPU-process RSS; not real-sensor accuracy or GPU performance.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True);p.add_argument('--side',type=int,default=4096);p.add_argument('--maximum-rss-mb',type=float,default=1024);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    try:result=run(args.work,args.side,maximum_rss_mb=args.maximum_rss_mb)
    except Exception as e:result={'passed':False,'error_type':type(e).__name__,'error':str(e)}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
