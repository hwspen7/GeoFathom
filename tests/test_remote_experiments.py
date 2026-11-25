"""Controlled common-support comparisons, archive replay and corruption rejection."""
import copy
import json
import time
from pathlib import Path
from uuid import uuid4
import zipfile
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from core.main import app
from imagery.remote_experiments import run_experiment,restore
from terrain.studio_data import FigureInputError
from test_remote_model import model_fixture


def experiments(config):
    return {**config,'archive_mb':256,'variants':[{'name':'All features','roles':list(config['features']),'trees':16},
        {'name':'Optical ablation','roles':['red'],'trees':16,'max_depth':4}]}


def test_experiments_share_support_and_archive_replays_models(tmp_path):
    config,_,_,_=model_fixture(tmp_path)
    with rasterio.open(config['features']['nir']['path'],'r+') as ds:
        z=ds.read(1);z[:3,:4]=np.nan;ds.write(z,1)
    archive=tmp_path/'experiment.zip';result=run_experiment(experiments(config),archive)
    assert result['common_training_cells']==957 and result['excluded_incomplete_cells']==3
    config,manifest=restore(archive,tmp_path/'restored');repeated=run_experiment(config,tmp_path/'repeated.zip')
    assert result['partition_sha256']==repeated['partition_sha256']
    assert [v['model_sha256'] for v in result['variants']]==[v['model_sha256'] for v in repeated['variants']]
    assert len({v['partition_sha256'] for v in result['variants']})==1
    assert all(v['validation']['cells']==957 for v in result['variants'])
    assert result['baseline']['overall_accuracy']==pytest.approx(1/3)
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    data,meta,table=render(StudioInput(recipe='grouped_bar',csv=result['comparison_csv'],x='variant',columns=['accuracy','macro_f1','mean_iou']))
    assert len(data)>100 and meta['used_count']>0
    with zipfile.ZipFile(archive) as source,zipfile.ZipFile(tmp_path/'corrupt.zip','w') as bad:
        for name in source.namelist():bad.writestr(name,b'bad' if name=='comparison.csv' else source.read(name))
    with pytest.raises(FigureInputError,match='checksum'):restore(tmp_path/'corrupt.zip',tmp_path/'bad-restore')
    assert not (tmp_path/'bad-restore').exists()


def test_experiment_cancellation_and_unsafe_archive_cleanup(tmp_path):
    config,_,_,_=model_fixture(tmp_path);out=tmp_path/'experiment.zip'
    def cancel(f):raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):run_experiment(experiments(config),out,cancel)
    assert not out.exists() and not list(tmp_path.glob('.experiment-*'))
    bad=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(bad,'w') as z:z.writestr('../escape','x');z.writestr('manifest.json','{}')
    with pytest.raises(FigureInputError,match='Unsafe'):restore(bad,tmp_path/'unsafe')
    assert not (tmp_path/'unsafe').exists()


@pytest.mark.parametrize('isolated',[False,True])
def test_managed_experiment_download_recipe_and_replay(tmp_path,monkeypatch,isolated):
    monkeypatch.setenv('GEOFATHOM_DATABASE_PATH',str(tmp_path/'experiment.sqlite'))
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path/'images'))
    monkeypatch.setenv('GEOFATHOM_MODEL_ADMIN_TOKEN','experiment-test')
    monkeypatch.setenv('GEOFATHOM_RASTER_ISOLATE','1' if isolated else '0')
    config,_,_,_=model_fixture(tmp_path);root=tmp_path/'images';root.mkdir();ids={}
    for p in [*[b['path'] for b in config['features'].values()],config['labels']['path']]:
        uid=str(uuid4());ids[p]=uid;(root/(uid+'.tif')).write_bytes(Path(p).read_bytes())
    payload={**experiments(config),'features':{r:{'image_id':ids[b['path']]} for r,b in config['features'].items()},'labels':{'image_id':ids[config['labels']['path']]}}
    headers={'X-GeoFathom-Admin-Token':'experiment-test'}
    with TestClient(app) as client:
        project=client.post('/projects',json={'name':'Experiments'}).json()['id'];url='/projects/'+project+'/jobs'
        response=client.post(url,json={'kind':'remote_experiment','payload':payload},headers=headers)
        assert response.status_code==202,response.text
        def wait(uid):
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                job=client.get(url+'/'+uid).json()
                if job['status'] in ('completed','failed','cancelled'):break
                time.sleep(.03)
            assert job['status']=='completed',job.get('error');return job
        first=wait(response.json()['id']);assert client.get(url+'/'+first['id']+'/download').headers['content-type']=='application/zip'
        assert client.post(url+'/'+first['id']+'/imagery',headers=headers).status_code==422
        assert client.get(url+'/'+first['id']+'/recipe').status_code==200
        repeated=client.post(url+'/'+first['id']+'/repeat',json={},headers=headers);assert repeated.status_code==202,repeated.text
        second=wait(repeated.json()['id']);assert second['result']['sha256']==first['result']['sha256']
