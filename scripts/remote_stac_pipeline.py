"""Pinned real Sentinel-2 L2A crops through native QA, cubes, NDVI and dated trends."""
import argparse
import base64
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from imagery.remote_scene import read_scene
from imagery.remote_cube import build_cube
from imagery.remote_windowed import process,digest
from analysis.science_raster import require

ITEMS=['S2A_T17TLE_20230603T162341_L2A','S2A_T17TLE_20230713T162016_L2A','S2A_T17TLE_20230723T162339_L2A','S2A_T17TLE_20230802T162332_L2A','S2A_T17TLE_20230822T163027_L2A','S2A_T17TLE_20230901T162408_L2A']
BBOX=[-83.018,39.999,-83.008,40.009]


def run(cache,out):
    cache=Path(cache);out=Path(out);cache.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    acquisitions=[];scenes=[]
    for item in ITEMS:
        saved=cache/(item+'.json')
        if saved.exists():scene=json.loads(saved.read_text())
        else:
            scene=read_scene('sentinel-2-c1-l2a',item,BBOX,['red','nir','scl']);saved.write_text(json.dumps(scene))
        require(scene['item_id']==item and scene['bbox']==BBOX,'Cached scene identity differs from the fixed benchmark.')
        bands={};qa=[]
        for band in scene['bands']:
            raw=base64.b64decode(band['data'],validate=True);path=cache/(item+'-'+band['role']+'.tif')
            import hashlib
            require(hashlib.sha256(raw).hexdigest()==band['sha256'],'Cached real-scene crop checksum mismatch.')
            if path.exists():require(digest(path)==band['sha256'],'Cached crop file changed.')
            else:path.write_bytes(raw)
            if band['role']=='scl':qa.append({'path':str(path),'scheme':'sentinel_clear'})
            else:
                dated=out/(item+'-'+band['role']+'.tif');dated.write_bytes(raw)
                with rasterio.open(dated,'r+') as ds:ds.update_tags(1,ACQUISITION_DATETIME=scene['acquired_at'])
                # Metadata-only date tagging changes the crop identity; retain both hashes.
                bands[band['role']]={'path':str(dated),'encoding':'raw'}
        acquisitions.append({'id':item,'sensor':'Sentinel-2A Collection-1 L2A','datetime':scene['acquired_at'],'bands':bands,'quality':qa})
        scenes.append({k:v for k,v in scene.items() if k!='bands'}|{'bands':[{k:v for k,v in b.items() if k!='data'} for b in scene['bands']]})
    cube=out/'cube.tif';receipt=build_cube({'target_path':acquisitions[0]['bands']['red']['path'],'acquisitions':acquisitions,'resampling':'bilinear'},cube)
    series=[];checks=[]
    with rasterio.open(cube) as ds:
        profile=ds.profile
        for i,item in enumerate(ITEMS):
            output=out/('ndvi-'+str(i)+'.tif');process('ndvi',{'red':{'path':str(cube),'band':2*i+1,'encoding':'raw'},'nir':{'path':str(cube),'band':2*i+2,'encoding':'raw'}},output,tile=64)
            red,nir=ds.read([2*i+1,2*i+2]);denominator=nir+red
            expected=np.divide(nir-red,denominator,out=np.full(red.shape,np.nan),where=np.isfinite(denominator)&(abs(denominator)>1e-12))
            with rasterio.open(output) as product:actual=product.read(1)
            require(np.array_equal(np.isfinite(actual),np.isfinite(expected)) and np.allclose(actual,expected,atol=1e-13,equal_nan=True),'Real-scene NDVI arithmetic disagrees with independent reference.')
            series.append(actual);checks.append({'item':item,'valid_cells':int(np.isfinite(actual).sum()),'sha256':digest(output)})
    stack=out/'ndvi-series.tif';profile.update(count=6)
    with rasterio.open(stack,'w',**profile) as ds:
        for i,z in enumerate(series):ds.write(z,i+1);ds.update_tags(i+1,TERRAIN_UNIT='unitless',ACQUISITION_DATETIME=acquisitions[i]['datetime'])
    slope=out/'ndvi-trend.tif';trend=process('series_slope',{'date'+str(i+1):{'path':str(stack),'band':i+1,'unit':'unitless','encoding':'raw'} for i in range(6)},slope,tile=64,times=receipt['times'])
    values=np.stack(series);expected=np.full(values.shape[1:],np.nan);times=np.asarray(receipt['times'])
    for row,col in zip(*np.nonzero(np.isfinite(values).sum(axis=0)>=3)):
        valid=np.isfinite(values[:,row,col]);matrix=np.column_stack((np.ones(valid.sum()),times[valid]));expected[row,col]=np.linalg.lstsq(matrix,values[valid,row,col],rcond=None)[0][1]
    with rasterio.open(slope) as ds:actual=ds.read(1);unit=ds.tags().get('TERRAIN_UNIT')
    require(np.isfinite(expected).any() and np.array_equal(np.isfinite(actual),np.isfinite(expected)) and np.allclose(actual,expected,atol=1e-12,equal_nan=True),'Actual-date NDVI trend differs from independent least squares.')
    finite=np.isfinite(actual);maximum=float(np.max(abs(actual[finite]-expected[finite])))
    return {'passed':True,'benchmark_sha256':digest(__file__),'collection':'sentinel-2-c1-l2a','bbox':BBOX,'scenes':scenes,'cube':receipt,'ndvi_checks':checks,
        'trend':{'paired_cells':int(finite.sum()),'maximum_absolute_error':maximum,'unit':unit,'sha256':digest(slope),'time_unit':'day','times':receipt['times']},
        'scope':'Real metadata-calibrated L2A radiometry, supplied SCL, dated cube and arithmetic/temporal integration; no independent vegetation or surface-reflectance field accuracy claim.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    try:result=run(args.cache,args.work)
    except Exception as e:result={'passed':False,'error_type':type(e).__name__,'error':str(e)}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps({'passed':result['passed'],'error':result.get('error'),'trend':result.get('trend')},indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
