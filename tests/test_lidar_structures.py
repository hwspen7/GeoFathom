import numpy as np
import pytest
from analysis.lidar_structures import cloth_filter,canopy_complexity,building_candidates

def test_cloth_flat_ground_and_obstacle():
    x,y=np.meshgrid(np.arange(9.),np.arange(9.))
    p=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    q=np.vstack((p,[4,4,5.]))
    out,m=cloth_filter(q,1.,3.,.2,60,1e-5)
    assert m["converged"]
    assert m["ground_points"]==81
    assert out[-1,4]==pytest.approx(5.)
    assert out[-1,5]==0

def test_cloth_bridges_single_elevated_cell():
    x,y=np.meshgrid(np.arange(9.),np.arange(9.))
    p=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    p[40,2]=5.
    out,m=cloth_filter(p,1.,3.,.2,100,1e-5)
    assert m["ground_points"]==80
    assert out[40,5]==0
    assert abs(out[40,3])<.2

def test_canopy_entropy_and_occupied_volume():
    p=np.array([[.1,.1,2.1],[.2,.2,2.2],[.3,.3,3.1],[.4,.4,3.2]])
    out,m=canopy_complexity(p,np.zeros(4),1.,1.,2.)
    assert out[0,4]==2
    assert out[0,5]==pytest.approx(np.log(2))
    assert out[0,6]==pytest.approx(2)
    assert out[0,7]==pytest.approx(2)
    assert m["occupied_voxel_volume_m3"]==pytest.approx(2)

def test_planar_roof_footprint_and_volume_proxy():
    x,y=np.meshgrid(np.arange(6.)+.2,np.arange(5.)+.2)
    p=np.column_stack((x.ravel(),y.ravel(),np.full(x.size,4.)))
    out,m=building_candidates(p,np.zeros(len(p)),1.,12,2.,.01,5)
    assert m["candidate_components"]==1
    assert m["occupied_area_m2"]==30
    assert m["height_volume_proxy_m3"]==120
    assert m["components"][0]["grid_perimeter_m"]==22
