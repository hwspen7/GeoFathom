"""Actual reviewed sample revisions, label reuse and geographic leakage rejection."""
import copy
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
from pyproj import Transformer
import pytest
import rasterio

from core.main import app
from imagery.remote_samples import SampleSet,raster_samples
from imagery.remote_model import train
from terrain.studio_data import FigureInputError
from test_remote_model import model_fixture


def sample_fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('GEOFATHOM_DATABASE_PATH',str(tmp_path/'samples.sqlite'))
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path/'managed'))
    monkeypatch.setenv('GEOFATHOM_MODEL_ADMIN_TOKEN','sample-test')
    config,arrays,_,truth=model_fixture(tmp_path);root=tmp_path/'managed';root.mkdir();features={}
    for role,band in config['features'].items():
        uid=str(uuid4());(root/(uid+'.tif')).write_bytes(Path(band['path']).read_bytes());features[role]={'image_id':uid}
    annotations=[]
    with rasterio.open(config['features']['red']['path']) as ds:
        transform=Transformer.from_crs(ds.crs,'EPSG:4326',always_xy=True)
        for row in range(48):
            for col in range(0,80,8):
                x=ds.transform.c+(col+.5)*ds.transform.a;y=ds.transform.f+(row+.5)*ds.transform.e;lon,lat=transform.transform(x,y)
                annotations.append({'id':str(row)+'-'+str(col),'geometry':{'type':'Point','coordinates':[lon,lat]},'class_id':int(truth[row,col]),'split':'train','review':'accepted','source':'Independent hand annotation fixture','reviewer':'reviewer fixture'})
        for row in range(3):
            x=ds.transform.c+4.5*ds.transform.a;y=ds.transform.f+(row+.5)*ds.transform.e;lon,lat=transform.transform(x,y)
            annotations.append({'id':'reference-'+str(row),'geometry':{'type':'Point','coordinates':[lon,lat]},'class_id':row+1,'split':'reference','review':'accepted','source':'Independent held-out annotation fixture','reviewer':'reviewer fixture'})
    body={'name':'Reviewed research samples','target_image_id':features['red']['image_id'],'classes':[{'id':c,'name':'Class '+str(c)} for c in (1,2,3)],'annotations':annotations,'training_reference_buffer_m':0}
    return body,features,root


def test_sample_revision_preflight_materialization_and_model_reuse(tmp_path,monkeypatch):
    body,features,root=sample_fixture(tmp_path,monkeypatch);headers={'X-GeoFathom-Admin-Token':'sample-test'}
    with TestClient(app) as client:
        project=client.post('/projects',json={'name':'Samples'}).json()['id'];url='/projects/'+project+'/remote-samples'
        saved=client.post(url,json=body,headers=headers);assert saved.status_code==201,saved.text
        revision=saved.json();assert len(revision['sha256'])==64
        params={'features':features,'quality':[],'parameters':{'block_m':40,'folds':5,'calibrate':True}}
        checked=client.post(url+'/'+revision['id']+'/preflight',json=params,headers=headers)
        assert checked.status_code==200,checked.text
        report=checked.json();assert report['ready'] and report['training_cells']==480 and report['reference_cells']==3
        labels=client.post(url+'/'+revision['id']+'/labels',headers=headers)
        assert labels.status_code==200,labels.text
        rasters=labels.json()['rasters'];config={'features':{r:{'path':str(root/(b['image_id']+'.tif'))} for r,b in features.items()},'labels':{'path':str(root/(rasters['train']['id']+'.tif'))},'parameters':{'block_m':40,'trees':16}}
        model=tmp_path/'model.json';train(config,model)
        artifact=json.loads(model.read_text());assert artifact['label_provenance']['SAMPLE_REVISION_SHA256']==revision['sha256']
        config['labels']['path']=str(root/(rasters['reference']['id']+'.tif'))
        with pytest.raises(FigureInputError,match='Reference-only'):train(config,tmp_path/'leaked.json')
        body['name']='Reviewed samples revised';new=client.post(url,json=body,headers=headers).json()
        assert new['sha256']!=revision['sha256']
        assert client.get(url+'/'+revision['id']).json()['body']['name']=='Reviewed research samples'
        other=client.post('/projects',json={'name':'Other'}).json()['id']
        assert client.get('/projects/'+other+'/remote-samples/'+revision['id']).status_code==404


def test_sample_geometries_reject_overlap_and_reference_buffer(tmp_path,monkeypatch):
    body,features,root=sample_fixture(tmp_path,monkeypatch)
    with rasterio.open(root/(features['red']['image_id']+'.tif')) as ds:
        overlap=copy.deepcopy(body);extra=copy.deepcopy(overlap['annotations'][0]);extra['id']='duplicate';overlap['annotations'].append(extra)
        with pytest.raises(FigureInputError,match='overlap'):raster_samples(SampleSet.model_validate(overlap),ds)
        body['training_reference_buffer_m']=50
        with pytest.raises(FigureInputError,match='exclusion buffer'):raster_samples(SampleSet.model_validate(body),ds)
        body['annotations'][0]['reviewer']=''
        with pytest.raises(FigureInputError,match='reviewer'):raster_samples(SampleSet.model_validate(body),ds)


def test_sample_preflight_reports_missing_fold_classes(tmp_path,monkeypatch):
    from imagery.remote_samples import preflight
    body,features,root=sample_fixture(tmp_path,monkeypatch)
    body['classes'].append({'id':4,'name':'Unsampled class'})
    paths={r:{'path':str(root/(b['image_id']+'.tif'))} for r,b in features.items()}
    report=preflight(SampleSet.model_validate(body),paths,[],{'block_m':40})
    assert not report['ready'] and report['class_support']['4']==0
