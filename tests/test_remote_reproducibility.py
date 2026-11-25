"""Repeat actual scientific jobs and reject input changes before/after scheduling."""
import base64
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
import pytest

from core.main import app
from jobs.reproducibility import canonical_hash,compatible
from test_remote_sensing import source


def fixture(tmp_path,monkeypatch,isolated=False):
    monkeypatch.setenv('GEOFATHOM_DATABASE_PATH',str(tmp_path/'repro.sqlite'))
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path/'images'))
    monkeypatch.setenv('GEOFATHOM_MODEL_ADMIN_TOKEN','recipe-test')
    monkeypatch.setenv('GEOFATHOM_RASTER_ISOLATE','1' if isolated else '0')
    root=tmp_path/'images';root.mkdir();ids=[str(uuid4()),str(uuid4())]
    for uid,value in zip(ids,(.6,.2)):(root/(uid+'.tif')).write_bytes(base64.b64decode(source(np.full((16,20),value))['data']))
    payload={'operation':'ndvi','bindings':{'nir':{'image_id':ids[0]},'red':{'image_id':ids[1]}}}
    return root,ids,payload


def finished(client,url,uid):
    until=time.monotonic()+25
    while time.monotonic()<until:
        job=client.get(url+'/'+uid).json()
        if job['status'] in ('completed','failed','cancelled'):return job
        time.sleep(.03)
    raise AssertionError('Scientific job did not finish.')


@pytest.mark.parametrize('isolated',[False,True])
def test_verified_recipe_repeat_and_input_change_rejection(tmp_path,monkeypatch,isolated):
    root,ids,payload=fixture(tmp_path,monkeypatch,isolated);headers={'X-GeoFathom-Admin-Token':'recipe-test'}
    with TestClient(app) as client:
        project=client.post('/projects',json={'name':'Reproducible research'}).json()['id'];url='/projects/'+project+'/jobs'
        queued=client.post(url,json={'kind':'remote_windowed','payload':payload},headers=headers)
        assert queued.status_code==202,queued.text
        original=finished(client,url,queued.json()['id']);assert original['status']=='completed',original.get('error')
        response=client.get(url+'/'+original['id']+'/recipe');assert response.status_code==200,response.text
        recipe=response.json();checksum=recipe.pop('recipe_sha256');assert checksum==canonical_hash(recipe)
        assert set(recipe['input_sha256'])==set(ids) and len(recipe['software']['source_tree_sha256'])==64
        assert client.post(url+'/'+original['id']+'/repeat',json={}).status_code==403
        repeated=client.post(url+'/'+original['id']+'/repeat',json={},headers=headers)
        assert repeated.status_code==202,repeated.text
        result=finished(client,url,repeated.json()['id']);assert result['status']=='completed',result.get('error')
        assert result['result']['sha256']==original['result']['sha256']
        assert result['result']['reproducibility']['repeated_from_job']==original['id']
        (root/(ids[0]+'.tif')).write_bytes(base64.b64decode(source(np.full((16,20),.8))['data']))
        denied=client.post(url+'/'+original['id']+'/repeat',json={},headers=headers)
        assert denied.status_code==422 and 'checksum changed' in denied.text


def test_repeat_checks_execution_snapshots_after_queue_time_mutation(tmp_path,monkeypatch):
    from jobs import queue
    from imagery.remote_managed import result_path
    root,ids,payload=fixture(tmp_path,monkeypatch);headers={'X-GeoFathom-Admin-Token':'recipe-test'}
    with TestClient(app) as client:
        project=client.post('/projects',json={'name':'Snapshot race'}).json()['id'];url='/projects/'+project+'/jobs'
        queued=client.post(url,json={'kind':'remote_windowed','payload':payload},headers=headers).json()
        original=finished(client,url,queued['id']);assert original['status']=='completed'
        monkeypatch.setenv('GEOFATHOM_EXTERNAL_WORKER','1')
        response=client.post(url+'/'+original['id']+'/repeat',json={},headers=headers)
        assert response.status_code==202,response.text
        repeated=response.json();assert repeated['status']=='queued'
        (root/(ids[0]+'.tif')).write_bytes(base64.b64decode(source(np.full((16,20),.9))['data']))
        queue._worker(repeated['id'],str(tmp_path/'repro.sqlite'))
        result=finished(client,url,repeated['id'])
        assert result['status']=='failed' and 'Scientific inputs changed' in result['error']
        assert not result_path(repeated['id']).exists()


def test_software_compatibility_checks_algorithm_and_numeric_environment():
    old={'source_tree_sha256':'a','python':'3.11','platform':'Linux','packages':{'numpy':'2'},'gdal':'3',
         'thread_configuration':{'OMP_NUM_THREADS':'1'},'geofathom_commit':'one'}
    assert compatible(old,{**old,'geofathom_commit':'two'})
    assert not compatible(old,{**old,'source_tree_sha256':'b'})
    other={**old,'thread_configuration':{'OMP_NUM_THREADS':'2'}}
    assert compatible(old,other,check_threads=False) and not compatible(old,other)
