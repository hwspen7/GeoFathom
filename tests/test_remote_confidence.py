"""Calibration uses spatially disjoint support; mixed physical units retain distance."""
import json
import numpy as np
import pytest
import rasterio
from scipy.special import softmax
from imagery.remote_confidence import fit_temperature,calibrated_probabilities,feature_support,support_distance
from imagery.remote_model import train,predict,forest_probabilities,compile_forest
from test_remote_model import model_fixture


def test_temperature_calibration_matches_independent_likelihood_search():
    logits=np.array([[2,-2],[-3,3],[4,-4],[-1,1],[3,-3],[-4,4]],float)
    truth=np.array([1,2,2,2,1,1]);p=softmax(logits,axis=1);t=fit_temperature(p,truth,np.array([1,2]))
    candidates=np.geomspace(.05,20,20000)
    losses=[-np.log(softmax(logits/c,axis=1)[np.arange(6),truth-1]).mean() for c in candidates]
    assert -np.log(calibrated_probabilities(p,t)[np.arange(6),truth-1]).mean()<=min(losses)+1e-6
    assert np.isfinite(calibrated_probabilities(np.array([[0.,1.]]),t)).all()


def test_standardized_feature_distance_is_invariant_to_physical_units():
    rng=np.random.default_rng(6);x=rng.normal(size=(200,3));x[:,2]*=10000
    scale=np.array([1.,1000.,.001]);a={'feature_support':feature_support(x)};b={'feature_support':feature_support(x*scale)}
    probe=x[:20]+np.array([1,2,1000])
    np.testing.assert_allclose(support_distance(probe,a),support_distance(probe*scale,b),rtol=1e-12,atol=1e-12)


def test_nested_spatial_calibration_portable_prediction_and_rejection(tmp_path):
    config,arrays,labels,truth=model_fixture(tmp_path);config['parameters']['calibrate']=True
    model=tmp_path/'calibrated.json';receipt=train(config,model);artifact=json.loads(model.read_text())
    assert receipt['probability_calibration']['method']=='spatial_oof_temperature'
    for row in receipt['validation']['folds']:
        assert row['fold']!=row['calibration_fold'] and row['calibration_cells']>0
        assert row['calibration_training_cells']<row['training_cells']
    out=tmp_path/'prediction.tif';result=predict({'model_path':str(model),'features':config['features'],'maximum_training_distance':.001},out)
    expected=calibrated_probabilities(forest_probabilities(compile_forest(artifact),arrays.reshape(3,-1).T),artifact['probability_calibration']['temperature'])
    with rasterio.open(out) as ds:
        np.testing.assert_allclose(ds.read([5,6,7]).reshape(3,-1).T,expected,atol=1e-12)
        assert np.isnan(ds.read(1)).all() and np.isfinite(ds.read(2)).all()
    assert result['abstained_cells']==truth.size and len(result['domain_diagnostics']['mean_shift_training_sd'])==3


def test_selective_accuracy_publication_figure():
    from terrain.studio_routes import StudioInput
    from terrain.studio_render import render
    body=StudioInput(recipe='remote_selective_accuracy',csv='coverage,accuracy,accepted\n1,.8,100\n.5,.9,50',x='coverage',y='accuracy',z='accepted')
    for fmt in ('png','svg'):
        data,meta,table=render(body.model_copy(update={'format':fmt}))
        assert len(data)>100 and meta['threshold_points']==2
