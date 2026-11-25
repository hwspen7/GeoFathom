import numpy as np
import pytest
from analysis.lidar_covariance import covariance_change
from analysis.lidar_reconstruction import poisson_grid

def test_covariance_change_instrument_floor_on_horizontal_plane():
    x,y=np.meshgrid(np.arange(-4.,5),np.arange(-4.,5))
    p=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
    out,m=covariance_change(p+[0,0,.5],p,np.array([[0.,0,0]]),12,2.1,2.,.1,.2,.05,5)
    assert m["tested_cores"]==1
    assert out[0,8]==pytest.approx(.5)
    assert out[0,9]==pytest.approx(2*.2**2/13)
    assert out[0,10]==pytest.approx(0)
    assert out[0,11]==pytest.approx(np.sqrt(2*.2**2/13+.05**2))
    assert out[0,15]<.05

def test_screened_poisson_reduces_sample_residual():
    pytest.importorskip("skimage")
    n=1000;i=np.arange(n);z=1-2*(i+.5)/n
    phi=np.pi*(3-np.sqrt(5))*i;r=np.sqrt(1-z*z)
    p=np.column_stack((r*np.cos(phi),r*np.sin(phi),z))
    table,m=poisson_grid(p,16,.15,screen_weight=2.,iterations=100,tolerance=1e-5)
    assert np.isfinite(table).all()
    assert m["screened_sample_rmse"]<=m["unscreened_sample_rmse"]+1e-10
    assert m["surface_area_m2"]==pytest.approx(4*np.pi,rel=.35)
    assert m["boundary_edges"]==0
