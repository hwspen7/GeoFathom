"""Independent confusion, geographic exclusion and block-bootstrap reference tests."""
import base64
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from imagery.remote_model import train,predict
from imagery.remote_model_validation import evaluate,block_intervals,scores
from terrain.studio_data import FigureInputError
from test_remote_model import model_fixture
from test_remote_sensing import source


def test_external_reference_error_map_and_probability_diagnostics(tmp_path):
    config,arrays,_,truth=model_fixture(tmp_path);model=tmp_path/'model.json';train(config,model)
    affine=from_origin(600000,4500000,10,10);features={}
    for r,z in zip(config['features'],arrays):
        path=tmp_path/('new-'+r+'.tif');path.write_bytes(base64.b64decode(source(z,aff=affine)['data']));features[r]={'path':str(path)}
    prediction=tmp_path/'prediction.tif';predict({'model_path':str(model),'features':features},prediction)
    reference=truth.copy();reference[:12,:20]=1+reference[:12,:20]%3
    labels=tmp_path/'reference.tif';labels.write_bytes(base64.b64decode(source(reference,aff=affine)['data']))
    params={'model_path':str(model),'prediction_path':str(prediction),'reference_path':str(labels),
        'reference_description':'Independent synthetic annotation oracle for software verification.',
        'block_m':40,'training_buffer_m':40,'replicates':100,'tile':32}
    out=tmp_path/'errors.tif';result=evaluate(params,out);m=result['metrics']
    expected=np.bincount((reference.ravel()-1)*3+truth.ravel()-1,minlength=9).reshape(3,3)
    np.testing.assert_array_equal(m['confusion_matrix_reference_rows'],expected)
    assert m['overall_accuracy']==pytest.approx(1-240/3840)
    assert m['training_excluded_cells']==0 and m['coverage']==1
    assert sum(r[2] for r in m['reliability'])==3840 and m['multiclass_brier']>0
    with rasterio.open(out) as ds:np.testing.assert_array_equal(ds.read(1),reference!=truth)
    assert all(np.isfinite(v).all() for v in m['interval95'].values())
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    intervals='metric,value,low,high\n'+'\n'.join(','.join(map(str,[key,m[key],*m['interval95'][key]])) for key in ('overall_accuracy','macro_f1','mean_iou'))
    reliability='predicted,observed,cells\n'+'\n'.join(','.join(map(str,r)) for r in m['reliability'])
    for body in (StudioInput(recipe='research_forest',csv=intervals,x='metric',y='value',low='low',high='high'),
                 StudioInput(recipe='remote_reliability',csv=reliability,x='predicted',y='observed',z='cells')):
        for fmt in ('png','svg'):
            data,meta,table=render(body.model_copy(update={'format':fmt}))
            assert len(data)>100 and meta['used_count']>0 and len(table)>1


def test_reference_rejects_training_reuse_and_excludes_training_locations(tmp_path):
    config,_,labels,truth=model_fixture(tmp_path);model=tmp_path/'model.json';train(config,model)
    prediction=tmp_path/'prediction.tif';predict({'model_path':str(model),'features':config['features']},prediction)
    params={'model_path':str(model),'prediction_path':str(prediction),'reference_path':config['labels']['path'],
        'reference_description':'Reference masks supplied separately for independence checks.','block_m':40,'training_buffer_m':0,'replicates':100}
    with pytest.raises(FigureInputError,match='training label file'):evaluate(params,tmp_path/'bad.tif')
    path=tmp_path/'all-labels.tif';path.write_bytes(base64.b64decode(source(truth)['data']));params['reference_path']=str(path)
    result=evaluate(params,tmp_path/'excluded.tif')['metrics']
    assert result['training_excluded_cells']==np.count_nonzero(labels)
    assert result['cells']==truth.size-np.count_nonzero(labels) and result['overall_accuracy']==1
    params['training_buffer_m']=40
    with pytest.raises(FigureInputError,match='No independent'):evaluate(params,tmp_path/'empty.tif')
    assert not (tmp_path/'empty.tif').exists() and not list(tmp_path.glob('.evaluation-*'))


def test_spatial_accuracy_intervals_match_independent_cluster_resampling():
    matrices=np.array([[[8+i,2],[1,9-i]] for i in range(8)],dtype=int)
    actual=block_intervals(matrices,100,73)
    rng=np.random.default_rng(73);oracle=[]
    for _ in range(100):
        total=matrices[rng.integers(0,8,size=8)].sum(axis=0)
        tp=np.diag(total);ref=total.sum(axis=1);pred=total.sum(axis=0)
        oracle.append([tp.sum()/total.sum(),np.mean(2*tp/(ref+pred)),np.mean(tp/(ref+pred-tp))])
    intervals=np.quantile(oracle,[.025,.975],axis=0)
    for i,name in enumerate(('overall_accuracy','macro_f1','mean_iou')):
        np.testing.assert_allclose(actual[name],intervals[:,i],atol=1e-12)
