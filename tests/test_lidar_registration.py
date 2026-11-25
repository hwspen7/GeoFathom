import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from analysis.lidar_registration import progressive_morphology,coarse_pca_registration,generalized_icp

def test_progressive_morphology_flat_ground_and_high_return():
    x,y=np.meshgrid(np.arange(9.),np.arange(9.))
    g=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    p=np.vstack((g,[4,4,5.]))
    out,m=progressive_morphology(p,1.,4.,.2)
    assert m["ground_points"]==len(g)
    assert m["nonground_points"]==1
    assert len(m["window_history"])==3
    assert out[-1,4]==pytest.approx(5.)

def test_coarse_pca_large_rotation_and_translation():
    rng=np.random.default_rng(20)
    ref=rng.normal(size=(500,3))*[5,2,1]
    source=ref@Rotation.from_euler("xyz",[70,35,110],degrees=True).as_matrix().T+[3,9,2]
    out,m=coarse_pca_registration(source,ref,.1,.9)
    assert m["orientation_candidates"]==24
    assert m["inlier_fraction"]==1
    np.testing.assert_allclose(out[:,:3],ref,atol=1e-10)

def test_gicp_covariance_registration():
    rng=np.random.default_rng(42)
    ref=rng.uniform(-4,4,(500,3))
    source=ref@Rotation.from_rotvec([.006,-.004,.003]).as_matrix().T+[.03,-.02,.01]
    out,m=generalized_icp(source,ref,12,.4,.9,50,1e-8,.01)
    assert m["converged"]
    assert m["inlier_fraction"]==1
    np.testing.assert_allclose(out[:,:3],ref,atol=1e-7)
