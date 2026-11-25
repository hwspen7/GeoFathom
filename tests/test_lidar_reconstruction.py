import base64
import numpy as np
import pytest
from analysis.lidar_reconstruction import progressive_tin,poisson_grid
from analysis.lidar_exports import mesh_obj,raster_grid

def test_progressive_tin_plane():
    x,y=np.meshgrid(np.arange(9.),np.arange(9.))
    g=np.column_stack((x.ravel(),y.ravel(),(.05*x+.02*y).ravel()))
    out,m=progressive_tin(np.vstack((g,[4,4,4.])),1.,4.,.2)
    assert m["ground_points"]==len(g)
    assert m["nonground_points"]==1
    assert out[-1,4]==pytest.approx(3.72)
    assert m["unsupported_points"]==0

def test_poisson_sphere():
    pytest.importorskip("skimage")
    n=1500;i=np.arange(n);z=1-2*(i+.5)/n
    phi=np.pi*(3-np.sqrt(5))*i;r=np.sqrt(1-z*z)
    p=np.column_stack((r*np.cos(phi),r*np.sin(phi),z))
    table,m=poisson_grid(p,16,.12)
    assert np.isfinite(table).all()
    assert m["triangles"]>100
    assert m["surface_area_m2"]==pytest.approx(4*np.pi,rel=.35)
    assert m["boundary_edges"]==0

def test_obj_geotiff_geometry_nodata():
    obj=mesh_obj(np.array([[0,0,0,1,0,0,0,1,0,.5]]))
    assert sum(s.startswith("v ") for s in obj.splitlines())==3
    assert sum(s.startswith("f ") for s in obj.splitlines())==1
    from rasterio.io import MemoryFile
    raw=raster_grid(np.array([[.5,.5,2.],[2.5,.5,-3.]]),["x_m","y_m","delta_z_m"],"delta_z_m",1.,32617)
    with MemoryFile(base64.b64decode(raw)) as mem, mem.open() as ds:
        assert ds.crs.to_epsg()==32617
        np.testing.assert_allclose(ds.read(1),[[2,np.nan,-3]],equal_nan=True)
        assert ds.transform.c==0
        assert ds.transform.f==1
