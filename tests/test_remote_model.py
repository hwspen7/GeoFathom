"""Portable inference equivalence, spatial sample isolation and model reuse."""
import base64
import json
from pathlib import Path
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import numpy as np
import pytest
import rasterio
from sklearn.ensemble import RandomForestClassifier

from core.main import app
from imagery.remote_model import train,predict,compile_forest,forest_probabilities
from imagery.remote_windowed import digest
from terrain.studio_data import FigureInputError
from test_remote_sensing import source


def model_fixture(root):
    rng=np.random.default_rng(17);row,col=np.indices((48,80));truth=1+row%3
    features={}
    arrays=[]
    for r in ('red','nir','slope'):
        z=.15+.3*(truth-1)+rng.normal(0,.015,truth.shape);arrays.append(z)
        path=root/(r+'.tif');path.write_bytes(base64.b64decode(source(z)['data']))
        features[r]={'path':str(path)}
    labels=np.where(col%4==0,truth,0);path=root/'labels.tif';path.write_bytes(base64.b64decode(source(labels)['data']))
    return {'features':features,'labels':{'path':str(path)},'parameters':{'trees':16,'block_m':40},'tile':32},np.stack(arrays),labels,truth


def test_saved_forest_matches_sklearn_and_streamed_prediction(tmp_path):
    config,arrays,labels,truth=model_fixture(tmp_path)
    model=tmp_path/'model.json';receipt=train(config,model)
    config['tile']=64;other=tmp_path/'other.json';train(config,other)
    assert digest(model)==digest(other)
    artifact=json.loads(model.read_text());compiled=compile_forest(artifact)
    x=arrays[:,labels>0].T;y=labels[labels>0]
    independent=RandomForestClassifier(n_estimators=16,max_depth=12,min_samples_leaf=2,
        class_weight='balanced',random_state=42,n_jobs=1).fit(x,y)
    probe=arrays.reshape(3,-1).T
    np.testing.assert_allclose(forest_probabilities(compiled,probe),independent.predict_proba(probe),atol=1e-12,rtol=0)
    assert receipt['validation']['overall_accuracy']==1
    assert all(f['buffer_excluded']>0 for f in receipt['validation']['folds'])
    output=tmp_path/'prediction.tif';result=predict({'model_path':str(model),'features':config['features'],'tile':32},output)
    with rasterio.open(output) as ds:
        np.testing.assert_array_equal(ds.read(1),truth)
        probabilities=ds.read([5,6,7]);np.testing.assert_allclose(probabilities.sum(axis=0),1)
        assert np.all(ds.read(3)>=0) and np.all(ds.read(4)>=0)
    assert result['valid_cells']==3840 and result['model_sha256']==digest(model)


def test_model_rejects_wrong_features_and_cleans_late_cancellation(tmp_path):
    config,_,_,_=model_fixture(tmp_path);model=tmp_path/'model.json';train(config,model)
    out=tmp_path/'out.tif'
    with pytest.raises(FigureInputError,match='trained feature roles'):
        predict({'model_path':str(model),'features':{'other':config['features']['red']}},out)
    def cancelled(f):raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):
        predict({'model_path':str(model),'features':config['features'],'tile':32},out,progress=cancelled)
    assert not out.exists() and not list(tmp_path.glob('.prediction-*'))
    artifact=json.loads(model.read_text());artifact['trees'][0]['left'][0]=0
    with pytest.raises(FigureInputError,match='forward'):compile_forest(artifact)


def test_managed_training_prediction_and_project_isolation(tmp_path,monkeypatch):
    from imagery.store import imagery_dir
    monkeypatch.setenv('GEOFATHOM_DATABASE_PATH',str(tmp_path/'model.sqlite'))
    monkeypatch.setenv('GEOFATHOM_IMAGERY_DIR',str(tmp_path/'imagery'))
    monkeypatch.setenv('GEOFATHOM_MODEL_ADMIN_TOKEN','model-test')
    # The separate cube fixture tests subprocess transport; this test inspects model identity contracts.
    monkeypatch.setenv('GEOFATHOM_RASTER_ISOLATE','0')
    config,_,_,truth=model_fixture(tmp_path);root=imagery_dir();root.mkdir();ids={}
    for p in [*[b['path'] for b in config['features'].values()],config['labels']['path']]:
        uid=str(uuid4());ids[p]=uid;(root/(uid+'.tif')).write_bytes(Path(p).read_bytes())
    features={r:{'image_id':ids[b['path']]} for r,b in config['features'].items()}
    payload={'features':features,'labels':{'image_id':ids[config['labels']['path']]},'parameters':config['parameters']}
    headers={'X-GeoFathom-Admin-Token':'model-test'}
    with TestClient(app) as client:
        project=client.post('/projects',json={'name':'Model research'}).json()['id'];url='/projects/'+project+'/jobs'
        def submit(kind,payload):
            response=client.post(url,json={'kind':kind,'payload':payload},headers=headers)
            assert response.status_code==202,response.text
            uid=response.json()['id'];until=time.monotonic()+20
            while time.monotonic()<until:
                job=client.get(url+'/'+uid).json()
                if job['status'] in ('completed','failed','cancelled'):break
                time.sleep(.03)
            assert job['status']=='completed',job.get('error');return job
        model=submit('remote_model_train',payload)
        data=client.get(url+'/'+model['id']+'/download');assert data.status_code==200
        assert 'model-input-' not in data.text
        predicted=submit('remote_model_predict',{'model_job_id':model['id'],'features':features})
        assert predicted['result']['model_sha256']==model['result']['sha256']
        assert client.get(url+'/'+predicted['id']+'/download').status_code==200
        reference_id=str(uuid4())
        (root/(reference_id+'.tif')).write_bytes(base64.b64decode(source(truth)['data']))
        evaluation=submit('remote_model_evaluate',{'prediction_job_id':predicted['id'],'reference_image_id':reference_id,
            'reference_description':'Independent dense reference fixture with training positions excluded.',
            'block_m':40,'training_buffer_m':0,'replicates':100})
        assert evaluation['result']['metrics']['training_excluded_cells']==960
        assert client.get(url+'/'+evaluation['id']+'/download').status_code==200
        other=client.post('/projects',json={'name':'Other'}).json()['id']
        assert client.post('/projects/'+other+'/jobs',json={'kind':'remote_model_predict',
            'payload':{'model_job_id':model['id'],'features':features}},headers=headers).status_code==404
