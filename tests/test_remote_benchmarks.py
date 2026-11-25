"""Benchmark transport integrity, authentic grid recovery and scene-scale oracles."""
import copy
from io import BytesIO
import json
from pathlib import Path
import zipfile
import base64
from contextlib import contextmanager
import hashlib
from PIL import Image
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from terrain.studio_data import FigureInputError
from scripts.remote_oscd_benchmark import member_bytes,prepare_city
from test_remote_sensing import source


def test_public_oscd_member_range_and_checksum_validation(monkeypatch):
    import urllib.request
    stream=BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('city/image.tif',b'known satellite member')
    content=stream.getvalue()
    with zipfile.ZipFile(BytesIO(content)) as z:item=z.getinfo('city/image.tif')
    spec={'offset':0,'name':item.filename,'compressed':item.compress_size,'compression':item.compress_type,'size':item.file_size,'crc':item.CRC,'sha256':hashlib.sha256(b'known satellite member').hexdigest()}
    class Response(BytesIO):
        status=206;headers={'Content-Range':'bytes 0-'+str(len(content)-1)+'/'+str(len(content))}
    def open_url(request,timeout):
        assert request.get_header('Range').startswith('bytes=0-');return Response(content)
    monkeypatch.setattr(urllib.request,'urlopen',open_url)
    assert member_bytes('https://example.com/public.zip',spec)==b'known satellite member'
    with pytest.raises(FigureInputError,match='checksum'):member_bytes('https://example.com/public.zip',{**spec,'sha256':'0'*64})
    Response.status=200
    with pytest.raises(FigureInputError,match='honor'):member_bytes('https://example.com/public.zip',spec)


def test_oscd_grid_recovery_requires_exact_original_anchor_and_label_legend(tmp_path,monkeypatch):
    root=tmp_path/'cache';folder=root/'members'/'city';(folder/'imgs_1').mkdir(parents=True)
    z=np.arange(32*48).reshape(32,48)+1000;aff=from_origin(35.4,33.9,.0001,.0001)
    anchor=folder/'imgs_1'/'anchor_B04.tif'
    with rasterio.open(anchor,'w',driver='GTiff',height=32,width=48,count=1,dtype='float64',transform=aff,crs='EPSG:4326') as ds:ds.write(z,1)
    for date in (1,2):
        for role in ('B04','B08'):
            path=folder/('imgs_'+str(date)+'_rect')/(role+'.tif');path.parent.mkdir(exist_ok=True)
            with rasterio.open(path,'w',driver='GTiff',height=32,width=48,count=1,dtype='uint16') as ds:ds.write((z if role=='B04' else z+300).astype('uint16'),1)
    (folder/'dates.txt').write_text('2016-09-29\n2017-08-29')
    truth=(1+np.indices(z.shape)[0]%2).astype('uint8');label=BytesIO()
    from rasterio.io import MemoryFile
    with MemoryFile() as memory:
        with memory.open(driver='GTiff',height=32,width=48,count=1,dtype='uint8') as ds:ds.write(truth,1)
        raw=memory.read()
    png=BytesIO();Image.fromarray(np.where(truth==2,255,0).astype('uint8')).save(png,format='PNG')
    with zipfile.ZipFile(root/'train-labels.zip','w') as zip:
        zip.writestr('labels/city/cm/city-cm.tif',raw);zip.writestr('labels/city/cm/cm.png',png.getvalue())
    features,labels,values,receipt=prepare_city(root,'city','train',tmp_path/'prepared')
    assert receipt['crs']=='EPSG:32636' and set(features)=={'red_before','red_after','nir_before','nir_after','red_difference','nir_difference'}
    assert np.isin(values[np.isfinite(values)],[1,2]).all() and np.isfinite(values).any()
    with rasterio.open(features['red_difference']['path']) as ds:assert np.all(ds.read(1,masked=True).compressed()==0)
    import scripts.remote_oscd_benchmark as oscd
    from scripts.remote_scene_reference import public_oscd_native
    monkeypatch.setattr(oscd,'obtain',lambda root,manifest:None)
    native=public_oscd_native(root,{'training_city':'city','dataset':'Synthetic transport fixture','source':'test'})
    assert native['passed'] and native['native_difference']['maximum_absolute_error']==0
    with rasterio.open(anchor,'r+') as ds:ds.write(z+1,1)
    with pytest.raises(FigureInputError,match='original anchor'):prepare_city(root,'city','train',tmp_path/'unproven')


def test_scene_scale_benchmark_verifies_all_pixels_and_masks(tmp_path):
    from scripts.remote_scene_scale import run
    result=run(tmp_path/'scale',128,tiles=(64,128),maximum_rss_mb=2048)
    assert result['passed'] and result['cells']==128**2
    assert all(c['mask_disagreement']==0 and c['maximum_absolute_error']==0 for c in result['checks'])
    assert result['checks'][0]['paired_cells']==result['checks'][1]['paired_cells']<128**2


def test_dated_stac_pipeline_preserves_cache_and_matches_independent_trend(tmp_path,monkeypatch):
    import scripts.remote_stac_pipeline as pipeline
    def scene(collection,item,bbox,roles):
        i=pipeline.ITEMS.index(item);bands=[]
        for role in roles:
            z=np.full((32,48),.2+.01*i if role=='red' else .5+.005*i if role=='nir' else 4.)
            raw=base64.b64decode(source(z)['data']);bands.append({'role':role,'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()})
        return {'collection':collection,'item_id':item,'bbox':bbox,'acquired_at':f'2023-0{i+1}-01T00:00:00Z','bands':bands}
    monkeypatch.setattr(pipeline,'read_scene',scene)
    first=pipeline.run(tmp_path/'cache',tmp_path/'run1');second=pipeline.run(tmp_path/'cache',tmp_path/'run2')
    assert first['passed'] and second['passed'] and first['trend']['paired_cells']==1536 and first['trend']['maximum_absolute_error']<1e-12
    assert first['trend']['sha256']==second['trend']['sha256']
