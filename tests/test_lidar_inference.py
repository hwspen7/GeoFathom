import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from analysis.lidar_inference import feature_registration,clustered_normal_change,_by_adjust,_cluster_variance,canopy_watershed,multiscale_geometry

def test_feature_registration_partial_overlap():
    rng=np.random.default_rng(22)
    shared=rng.uniform(-2,2,(180,3))
    a=np.vstack((shared,rng.uniform(15,18,(40,3))))
    b=np.vstack((shared,rng.uniform(-18,-15,(50,3))))
    a=a@Rotation.from_euler("xyz",[45,25,80],degrees=True).as_matrix().T+[6,-2,3]
    out,m=feature_registration(a,b,8,.001,.8,60,8)
    np.testing.assert_allclose(out[:180,:3],shared,atol=1e-10)
    assert m["source_overlap_fraction"]==pytest.approx(180/220)
    assert m["reference_overlap_fraction"]==pytest.approx(180/230)

def test_cluster_variance_and_by_reference():
    x=np.array([0.,0.,1.,1.,2.,2.]);xy=np.column_stack((np.repeat([.1,1.1,2.1],2),np.zeros(6)))
    var,g=_cluster_variance(x,xy,1.)
    assert g==3
    assert var==pytest.approx(1/3)
    np.testing.assert_allclose(_by_adjust([.01,.04,.03,np.nan]),[.055,.07333333333333333,.07333333333333333,np.nan],equal_nan=True)

def test_clustered_normal_change_parallel_planes_and_block_support():
    x,y=np.meshgrid(np.arange(-5.,6),np.arange(-5.,6))
    p=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    cores=np.array([[0.,0,0],[50,50,0]])
    out,m=clustered_normal_change(p+[0,0,.5],p,cores,12,3.,2.,1.5,.05,5)
    assert m["tested_cores"]==1
    assert out[0,10]==pytest.approx(.5)
    assert out[0,17]==1
    assert np.isnan(out[1,16])
    variance,groups=_cluster_variance(np.array([0.,1.,2.]),np.array([[.1,.1],[.2,.2],[.3,.3]]),1.)
    assert groups==1 and np.isnan(variance)

def test_watershed_does_not_bridge_unobserved_cells():
    p=np.array([[.1,.1,5],[1.1,.1,4],[2.1,.1,3],[4.1,.1,6],[5.1,.1,4]])
    out,m=canopy_watershed(p,np.zeros(len(p)),1.,2.1,2.)
    assert m["candidate_crowns"]==2
    assert len(set(out[:3,3]))==1 and len(set(out[3:,3]))==1
    assert out[0,3]!=out[-1,3]
    assert sum(c["occupied_footprint_m2"] for c in m["crowns"])==5

def test_multiscale_planar_normal_and_degenerate_line():
    x,y=np.meshgrid(np.arange(9.),np.arange(9.))
    p=np.column_stack((x.ravel(),y.ravel(),(x+2*y).ravel()))
    out,m=multiscale_geometry(p,12)
    assert m["valid_points"]==len(p)
    np.testing.assert_allclose(out[:,6:9],np.tile(np.array([-1,-2,1])/np.sqrt(6),(len(p),1)),atol=1e-10)
    _,m=multiscale_geometry(np.column_stack((np.arange(20.),np.zeros((20,2)))),12)
    assert m["valid_points"]==0
