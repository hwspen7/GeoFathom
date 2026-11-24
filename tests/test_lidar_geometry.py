import numpy as np
import pytest
from analysis.lidar_geometry import ground_filter,tin_mesh,alpha_boundary,plane_icp,roof_planes,crown_candidates

def test_ground_filter_plane_and_elevated_return():
    x,y=np.meshgrid(np.arange(7.),np.arange(7.))
    ground=np.column_stack((x.ravel(),y.ravel(),(.1*x+.1*y).ravel()))
    p=np.vstack((ground,[3,3,5.6]))
    out,m=ground_filter(p,1.,3.,.15)
    assert m["ground_points"]==len(ground)
    assert m["nonground_points"]==1
    assert out[-1,4]==pytest.approx(5.)

def test_tin_analytic_plane_area_and_edge_rejection():
    p=np.array([[0.,0,0],[1,0,1],[0,1,2],[1,1,3]])
    _,m=tin_mesh(p,4.)
    assert m["projected_area_m2"]==pytest.approx(1)
    assert m["surface_area_m2"]==pytest.approx(np.sqrt(6))
    with pytest.raises(ValueError):tin_mesh(p,.1)

def test_alpha_tetrahedron_volume_and_outward_faces():
    p=np.array([[0.,0,0],[1,0,0],[0,1,0],[0,0,1]])
    out,m=alpha_boundary(p,1.)
    assert m["volume_m3"]==pytest.approx(1/6)
    assert m["boundary_faces"]==4
    for row in out:
        v=row[:9].reshape(3,3)
        assert np.dot(np.cross(v[1]-v[0],v[2]-v[0]),p.mean(axis=0)-v[0])<0
    with pytest.raises(ValueError):alpha_boundary(p,.1)

def test_point_plane_icp_rejects_flat_unobservable_cloud():
    x,y=np.meshgrid(np.arange(8.),np.arange(8.))
    p=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    with pytest.raises(ValueError,match="observable"):plane_icp(p,p,8,1.,1.,10,1e-6)

def test_point_plane_icp_three_orthogonal_surfaces():
    x,y=np.meshgrid(np.linspace(1,5,9),np.linspace(1,5,9))
    a=x.ravel();b=y.ravel();z=np.zeros(len(a))
    ref=np.vstack((np.column_stack((a,b,z)),np.column_stack((a,z,b)),np.column_stack((z,a,b))))
    source=ref+[.04,-.03,.05]
    out,m=plane_icp(source,ref,8,.3,1.,30,1e-8)
    assert m["converged"]
    np.testing.assert_allclose(out[:,:3],ref,atol=1e-7)

def test_plane_ransac_and_crown_assignment():
    x,y=np.meshgrid(np.arange(6.),np.arange(6.))
    p=np.column_stack((x.ravel(),y.ravel(),(2*x+1).ravel()))
    out,m=roof_planes(p,.001,15,40,3)
    assert len(m["planes"])==1
    assert m["unassigned_points"]==0
    assert m["planes"][0]["inclination_deg"]==pytest.approx(np.degrees(np.arctan(2)))
    pts=np.array([[.1,.1,5],[.2,.2,3],[5.1,.1,7],[5.2,.2,4],[20,20,1.]])
    out,m=crown_candidates(pts,np.zeros(len(pts)),1.,2.,2.)
    assert m["candidate_apices"]==2
    assert m["assigned_returns"]==4
    assert np.isnan(out[-1,4])
