"""Acquisition identities, pre-warp QA, disk parity and managed cube lifecycle."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
import pytest
import rasterio

from core.main import app
from imagery.remote_cube import build_cube
from imagery.remote_cube_managed import validate
from imagery.remote_windowed import process
from terrain.studio_data import FigureInputError
from test_remote_sensing import source, AFF


def cube_fixture(root, roles=('red','nir')):
    times=[0,2,5,9,14,20];acquisitions=[]
    for i,t in enumerate(times):
        bands={}
        for j,role in enumerate(roles):
            path=root/(f'{i}-{role}.tif')
            values=np.full((64,96),.2+j*.1+.01*t)
            path.write_bytes(base64.b64decode(source(values)['data']))
            bands[role]={'path':str(path)}
        qa=root/(str(i)+'-qa.tif');z=np.full((64,96),4.)
        if i==1:z[:8,:8]=9
        qa.write_bytes(base64.b64decode(source(z)['data']))
        acquisitions.append({'id':'date-'+str(i),'datetime':(datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(days=t)).isoformat(),
            'sensor':'fixture','bands':bands,'quality':[{'path':str(qa),'scheme':'sentinel_clear'}]})
    return {'target_path':acquisitions[0]['bands'][roles[0]]['path'],'acquisitions':acquisitions,'tile':32}


def test_disk_cube_dates_missingness_counts_and_temporal_reuse(tmp_path):
    config=cube_fixture(tmp_path)
    first=tmp_path/'cube.tif';receipt=build_cube(config,first)
    config['tile']=64;second=tmp_path/'other.tif';build_cube(config,second)
    assert receipt['times']==[0,2,5,9,14,20] and receipt['time_unit']=='day'
    with rasterio.open(first) as a,rasterio.open(second) as b:
        np.testing.assert_allclose(a.read(),b.read(),equal_nan=True)
        assert a.transform==AFF and a.count==14
        assert a.tags(3)['ACQUISITION_DATETIME']==config['acquisitions'][1]['datetime']
        assert np.isnan(a.read(3)[:8,:8]).all()
        count=a.read(receipt['support_bands']['red'])
        assert np.all(count[:8,:8]==5) and np.all(count[8:]==6)
    selected=[r for r in receipt['band_layout'] if r['role']=='red']
    bindings={f'date{i+1}':{'path':str(first),'band':entry['band'],'unit':'reflectance'} for i,entry in enumerate(selected)}
    result=tmp_path/'slope.tif';process('series_slope',bindings,result,times=receipt['times'],tile=64)
    with rasterio.open(result) as ds:np.testing.assert_allclose(ds.read(1),.01,atol=1e-12)


def test_disk_cube_rejects_ambiguous_dates_and_cleans_cancellation(tmp_path):
    config=cube_fixture(tmp_path);out=tmp_path/'cancelled.tif'
    def cancel():raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):build_cube(config,out,check=cancel)
    assert not out.exists() and not list(tmp_path.glob('.cube-*'))
    config['acquisitions'][1]['datetime']=config['acquisitions'][0]['datetime']
    with pytest.raises(FigureInputError,match='increasing UTC'):build_cube(config,out)
    config['acquisitions'][1]['datetime']='2024-01-02T00:00:00'
    with pytest.raises(FigureInputError,match='timezone'):build_cube(config,out)


@pytest.mark.parametrize('isolated',[False,True])
def test_managed_cube_job_download_register_and_reuse(tmp_path,monkeypatch,isolated):
    from imagery.store import imagery_dir
    monkeypatch.setenv('GEOFATHOM_DATABASE_PATH',str(tmp_path/'cube.sqlite'))
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path/'imagery'))
    monkeypatch.setenv('GEOFATHOM_MODEL_ADMIN_TOKEN','cube-test')
    monkeypatch.setenv('GEOFATHOM_RASTER_ISOLATE','1' if isolated else '0')
    config=cube_fixture(tmp_path,('red','nir','blue','green'))
    root=imagery_dir();root.mkdir()
    ids={}
    for path in {config['target_path'],*[b['path'] for a in config['acquisitions'] for b in a['bands'].values()],
                 *[q['path'] for a in config['acquisitions'] for q in a['quality']]}:
        uid=str(uuid4());ids[path]=uid;(root/(uid+'.tif')).write_bytes(Path(path).read_bytes())
    payload={'target_image_id':ids[config['target_path']],'acquisitions':[{**a,
        'bands':{r:{'image_id':ids[b['path']]} for r,b in a['bands'].items()},
        'quality':[{'image_id':ids[q['path']],'scheme':q['scheme']} for q in a['quality']]}
        for a in config['acquisitions']]}
    validate(payload)
    headers={'X-GeoFathom-Admin-Token':'cube-test'}
    with TestClient(app) as client:
        project=client.post('/projects',json={'name':'Cube research'}).json()['id']
        url='/projects/'+project+'/jobs'
        assert client.post(url,json={'kind':'remote_cube','payload':payload}).status_code==403
        response=client.post(url,json={'kind':'remote_cube','payload':payload},headers=headers)
        assert response.status_code==202,response.text
        uid=response.json()['id'];job=None
        until=time.monotonic()+20
        while time.monotonic()<until:
            job=client.get(url+'/'+uid).json()
            if job['status'] in ('completed','failed','cancelled'):break
            time.sleep(.03)
        assert job['status']=='completed',job
        assert job['result']['acquisition_count']==6 and 'cube-input-' not in json.dumps(job['result'])
        assert client.get(url+'/'+uid+'/download').status_code==200
        image=client.post(url+'/'+uid+'/imagery',headers=headers)
        assert image.status_code==201,image.text
        assert image.json()['bands']==28
        other=client.post('/projects',json={'name':'Other'}).json()['id']
        assert client.post('/projects/'+other+'/jobs/'+uid+'/imagery',headers=headers).status_code==404
