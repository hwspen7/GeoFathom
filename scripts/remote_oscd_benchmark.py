"""Real OSCD annotations through preparation, spatial training and external-site evaluation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
import sys
import urllib.request
import zipfile
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import calculate_default_transform,reproject,Resampling
from analysis.science_raster import require
from imagery.remote_windowed import digest

DEFAULT_MANIFEST=Path(__file__).resolve().parents[1]/'docs/benchmarks/oscd-manifest.json'


def member_bytes(url,item):
    start=item['offset'];end=start+30+len(item['name'].encode())+65535+item['compressed']-1
    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}','User-Agent':'GeoFathom scientific OSCD benchmark/1'})
    with urllib.request.urlopen(req,timeout=60) as response:
        require(response.status==206 and response.headers.get('Content-Range','').startswith(f'bytes {start}-'),'OSCD server must honor the pinned byte range.')
        data=response.read(end-start+2)
    require(len(data)<=end-start+1 and len(data)>=30,'Invalid ranged image response size.')
    header=struct.unpack('<4s5H3L2H',data[:30]);offset=30+header[-2]+header[-1]
    require(header[0]==b'PK\x03\x04' and data[30:30+header[-2]].decode()==item['name'] and header[3]==item['compression'],'ZIP local member differs from pinned manifest.')
    payload=data[offset:offset+item['compressed']]
    # Bound decompression before allocating a result or trusting ZIP metadata.
    if item['compression']==8:
        decoder=zlib.decompressobj(-15);raw=decoder.decompress(payload,item['size']+1)
        require(decoder.eof and not decoder.unconsumed_tail,'Unexpected compressed OSCD member length.')
    else:
        require(item['compression']==0,'Unsupported image archive compression.');raw=payload
    require(len(raw)==item['size'] and zlib.crc32(raw)==item['crc'] and hashlib.sha256(raw).hexdigest()==item['sha256'],'OSCD image member checksum mismatch.')
    return raw


def obtain(root,manifest):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    require(len(manifest['imagery_archive']['members'])<=32,'OSCD member count exceeds the download budget.')
    def image(item):
        relative=Path(item['destination'])
        require(not relative.is_absolute() and '..' not in relative.parts and relative.as_posix()==item['destination'] and 0<item['size']<=16*1024**2 and 0<item['compressed']<=16*1024**2,'Invalid OSCD destination or member size.')
        dest=root/'members'/item['destination']
        if dest.exists():require(digest(dest)==item['sha256'],'Cached OSCD member checksum mismatch.');return
        raw=member_bytes(manifest['imagery_archive']['url'],item);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(image,manifest['imagery_archive']['members']))
    for a in manifest['label_archives']:
        dest=root/a['filename']
        if not dest.exists():
            with urllib.request.urlopen(a['url'],timeout=60) as response:raw=response.read(2*1024*1024+1)
            require(len(raw)<=2*1024*1024 and hashlib.sha256(raw).hexdigest()==a['sha256'],'OSCD label archive checksum mismatch.');dest.write_bytes(raw)
        require(digest(dest)==a['sha256'],'Cached OSCD label archive checksum mismatch.')


def prepare_city(root,city,split,out):
    out.mkdir(parents=True,exist_ok=True);folder=root/'members'/city
    # The rectified images omit georeferencing. Recover it only after proving
    # exact pixel equality against the georeferenced original first red band.
    anchor=next((folder/'imgs_1').glob('*_B04.tif'))
    with rasterio.open(anchor) as source,rasterio.open(folder/'imgs_1_rect'/'B04.tif') as rect:
        require(source.crs and source.shape==rect.shape and np.array_equal(source.read(1),rect.read(1)),'Cannot establish the rectified benchmark grid from its original anchor.')
        native_crs=source.crs;native_transform=source.transform;shape=source.shape;bounds=source.bounds
        center=(bounds.left+bounds.right)/2;latitude=(bounds.bottom+bounds.top)/2
        zone=int((center+180)//6)+1;crs=rasterio.crs.CRS.from_epsg((32600 if latitude>=0 else 32700)+zone)
        transform,width,height=calculate_default_transform(native_crs,crs,source.width,source.height,*bounds,resolution=10)
    require(width*height<=2_000_000,'OSCD city exceeds the bounded benchmark grid.')
    with zipfile.ZipFile(root/(split+'-labels.zip')) as archive:
        label=next(n for n in archive.namelist() if n.endswith('/'+city+'-cm.tif'))
        with MemoryFile(archive.read(label)) as memory,memory.open() as ds:truth=ds.read(1)
        png=np.asarray(Image.open(BytesIO(archive.read(label.rsplit('/',1)[0]+'/cm.png'))))
        if png.ndim==3:png=png[:,:,:3];require(np.all(png==png[:,:,:1]),'Unexpected RGB label legend.');png=png[:,:,0]
        require(truth.shape==shape and np.isin(truth,[1,2]).all() and np.array_equal(truth==2,png==255) and np.array_equal(truth==1,png==0),'OSCD TIFF codes conflict with the published binary PNG legend.')
    def write(name,native,unit,categorical=False):
        values=np.full((height,width),np.nan)
        reproject(native.astype(float),values,src_crs=native_crs,src_transform=native_transform,dst_crs=crs,dst_transform=transform,
            src_nodata=np.nan,dst_nodata=np.nan,resampling=Resampling.nearest if categorical else Resampling.bilinear)
        path=out/(name+'.tif')
        with rasterio.open(path,'w',driver='GTiff',height=height,width=width,count=1,dtype='float64',crs=crs,transform=transform,nodata=np.nan,compress='deflate') as ds:ds.write(values,1);ds.update_tags(TERRAIN_UNIT=unit)
        return path,values
    feature_specs={};values={}
    for date in (1,2):
        for band in ('B04','B08'):
            name=('red' if band=='B04' else 'nir')+('_before' if date==1 else '_after')
            with rasterio.open(folder/('imgs_'+str(date)+'_rect')/(band+'.tif')) as ds:
                require(ds.shape==shape,'Rectified bands and labels differ.');native=ds.read(1)
            path,values[name]=write(name,native,'DN');feature_specs[name]={'path':str(path),'quantity':'numeric','unit':'DN'}
    for role in ('red','nir'):
        # Difference on the explicitly prepared common grid, without claiming BOA reflectance.
        path=out/(role+'_difference.tif');z=values[role+'_after']-values[role+'_before']
        with rasterio.open(path,'w',driver='GTiff',height=height,width=width,count=1,dtype='float64',crs=crs,transform=transform,nodata=np.nan,compress='deflate') as ds:ds.write(z,1);ds.update_tags(TERRAIN_UNIT='DN')
        feature_specs[role+'_difference']={'path':str(path),'quantity':'numeric','unit':'DN'}
    label_path,labels=write('reference',truth,'class',True)
    return feature_specs,label_path,labels,{'city':city,'original_split':split,'shape':[height,width],'crs':str(crs),'transform':list(transform)[:6],
        'native_crs':str(native_crs),'native_transform':list(native_transform)[:6],'anchor_sha256':digest(anchor),'dates_record':(folder/'dates.txt').read_text(),
        'grid_proof':'Exact first-date red equality between rectified array and georeferenced original; all rectified band/label shapes verified.',
        'resampling':{'numeric_DN':'bilinear','labels':'nearest'},'legend':'1 unchanged, 2 urban change; pixel-wise checked against PNG 0/255.'}


def run(root,out,manifest):
    from imagery.remote_model import train,predict
    from imagery.remote_model_validation import evaluate
    from jobs.reproducibility import software_record
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True);obtain(root,manifest)
    features,labels,truth,training=prepare_city(root,manifest['training_city'],'train',out/'training')
    test_features,reference,_,test=prepare_city(root,manifest['test_city'],'test',out/'independent-test')
    stride=manifest['sampling_stride'];rr,cc=np.indices(truth.shape);selected=(rr%stride==0)&(cc%stride==0)&np.isfinite(truth)
    with rasterio.open(labels) as source:
        profile=source.profile;sample=out/'training-samples.tif'
        with rasterio.open(sample,'w',**profile) as dst:dst.write(np.where(selected,truth,np.nan),1);dst.update_tags(TERRAIN_UNIT='class',SAMPLE_SPLIT='train')
    model=out/'model.json';source_names={spec['path']:'training/'+role+'.tif' for role,spec in features.items()};source_names[str(sample)]='training-samples.tif'
    trained=train({'features':features,'labels':{'path':str(sample)},'parameters':manifest['parameters'],'source_names':source_names},model)
    prediction=out/'independent-prediction.tif';predicted=predict({'features':test_features,'model_path':str(model)},prediction)
    errors=out/'independent-errors.tif';evaluated=evaluate({'model_path':str(model),'prediction_path':str(prediction),'reference_path':str(reference),
        'reference_description':'OSCD public test-city urban change annotations, disjoint from the fixed training-city subset.','block_m':100,'training_buffer_m':100,'replicates':500},errors)
    return {'passed':True,'benchmark_sha256':digest(__file__),'dataset':manifest['dataset'],'source':manifest['source'],'citation':manifest['citation'],'label_license':manifest['label_license'],
        'manifest_sha256':hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),'training':training,'independent_test':test,
        'sampling':{'rule':'Fixed regular grid, independent of class identity','stride':stride,'training_cells':int(selected.sum()),'class_support':{str(int(c)):int(np.sum(truth[selected]==c)) for c in np.unique(truth[selected])}},
        'spatial_validation':trained['validation'],'independent_metrics':evaluated['metrics'],'domain_diagnostics':predicted['domain_diagnostics'],
        'unchanged_baseline':{'overall_accuracy':evaluated['metrics']['support'][0]/evaluated['metrics']['cells'],'change_f1':0.,'scope':'All test observations labeled unchanged; highlights class imbalance.'},
        'software':software_record(),'model_sha256':digest(model),'prediction_sha256':digest(prediction),'error_sha256':digest(errors),
        'scope':'Real human-labeled two-city OSCD transfer subset with raw registered L1C DN features. Not the full OSCD leaderboard, calibrated surface-reflectance validation or external field certification.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--work',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--manifest',type=Path,default=DEFAULT_MANIFEST);args=parser.parse_args()
    try:result=run(args.cache,args.work,json.loads(args.manifest.read_text()))
    except Exception as e:result={'passed':False,'error_type':type(e).__name__,'error':str(e),'scope':'Public annotation validation did not complete; no accuracy claim.'}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps({'passed':result['passed'],'error':result.get('error'),'independent_metrics':result.get('independent_metrics')},indent=2));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
