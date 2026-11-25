import numpy as np
import pytest
from analysis.lidar_advanced import register, normal_change, robust_outlier, canopy_structure

def test_rigid_registration_known_small_transform():
    rng=np.random.default_rng(2026)
    ref=rng.uniform(-10,10,(400,3))+[500000,4400000,100]
    center=ref.mean(axis=0)
    angle=.008
    r=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1.]])
    source=(ref-center)@r.T+center+[.1,-.2,.05]
    table,metrics=register(source,ref,2.,.9,80,1e-7)
    assert metrics["converged"]
    np.testing.assert_allclose(table[:,:3],ref,atol=2e-7)
    assert metrics["inlier_rmse_m"]<2e-7
    rotation=np.asarray(metrics["rotation_matrix"])
    assert np.linalg.det(rotation)==pytest.approx(1.)
    np.testing.assert_allclose(source@rotation.T+metrics["translation_m"],ref,atol=2e-7)

def test_registration_rejects_degenerate_or_nonoverlap():
    line=np.column_stack((np.arange(5.),np.zeros((5,2))))
    with pytest.raises(ValueError):register(line,line,1.,1.,10,1e-6)
    with pytest.raises(ValueError):register(line,line+100,1.,1.,10,1e-6)

def test_normal_change_known_parallel_surfaces_and_lod():
    x,y=np.meshgrid(np.arange(-5.,6),np.arange(-5.,6))
    baseline=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    current=baseline+[0,0,.5]
    cores=np.array([[0.,0,0],[2,2,0],[50,50,0]])
    out,m=normal_change(current,baseline,cores,12,2.1,2.,.1,5)
    np.testing.assert_allclose(out[:2,8],.5)
    np.testing.assert_allclose(out[:2,9],.195996398454,rtol=1e-6)
    assert m["valid_cores"]==2
    assert m["above_detection_limit"]==2
    assert np.isnan(out[2,8])
    _,m=normal_change(current,baseline,cores[:1],12,2.1,2.,1.,5)
    assert m["above_detection_limit"]==0

def test_robust_outlier_and_canopy():
    x,y=np.meshgrid(np.arange(5.),np.arange(5.))
    cloud=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    p=np.vstack((cloud,[100,100,100]))
    out,m=robust_outlier(p,4,3.5)
    assert out[-1,2]==1
    assert m["flagged_points"]>=1
    pts=np.array([[.1,.1,1.],[.2,.2,3.],[.3,.3,5.],[1.1,.1,9.]])
    c,m=canopy_structure(pts,np.array([0.,0.,0.,np.nan]),1.,2.)
    assert c.shape==(1,11)
    assert c[0,2]==3
    assert c[0,5]==3
    assert c[0,-1]==pytest.approx(2/3)
    assert m["unsupported_returns"]==1
