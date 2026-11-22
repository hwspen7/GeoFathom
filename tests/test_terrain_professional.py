"""Analytical fixtures verify physical units, nodata, D8 and exact raster exports."""
import base64
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from terrain.professional import derivatives,d8_flow,least_cost,raster_product,classification
from imagery.raster import RasterError

def test_planar_derivatives_and_holes():
    z=np.tile(np.arange(7)*10.,(7,1));valid=np.ones_like(z,bool)
    d=derivatives(z,valid,10,10)
    assert d["slope_map"][3,3]==pytest.approx(45)
    assert d["aspect_map"][3,3]==pytest.approx(270)
    assert d["tri"][3,3]==pytest.approx(np.sqrt(600))
    assert d["tpi"][3,3]==pytest.approx(0)
    assert d["curvature"][3,3]==pytest.approx(0)
    assert np.isnan(d["slope_map"][0]).all()
    valid[3,3]=False
    assert np.isnan(derivatives(z,valid,10,10)["slope_map"][2:5,2:5]).all()

def test_d8_flow_plane_and_sink():
    z=np.tile(np.arange(5,dtype=float),(5,1))
    dst,direction,accum=d8_flow(z,np.ones_like(z,bool),1,1)
    assert np.all(direction[:,1:]==16) and np.all(direction[:,0]==0)
    assert np.all(dst[:,0]==-1)
    assert np.all(accum==np.tile([5,4,3,2,1],(5,1)))

def test_route_respects_nodata_and_grade():
    z=np.zeros((5,5));valid=np.ones_like(z,bool)
    valid[2,1:4]=False
    path,cost=least_cost(z,valid,(0,0),(4,4),1,1,30)
    assert path[0]==(0,0) and path[-1]==(4,4) and all(valid[p] for p in path)
    assert cost>=np.sqrt(32)
    with pytest.raises(RasterError,match="No valid"):
        least_cost(z,np.eye(5,dtype=bool),(0,0),(4,4),1,1,30)
    with pytest.raises(RasterError,match="slope limit"):
        least_cost(z,valid,(0,0),(4,4),1,1,0)

def test_real_geotiff_export_and_preview():
    z=np.array([[1.,2.],[3.,np.nan]])
    affine=from_origin(500000,4500000,10,10)
    p=raster_product(z,"elevation",affine,"EPSG:32617")
    assert p["valid_cells"]==3 and sum(b["cells"] for b in p["legend"])==3
    assert p["png"].startswith("data:image/png;base64,") and len(p["corners"])==4
    with MemoryFile(base64.b64decode(p["geotiff"])) as mem:
        with mem.open() as src:
            assert src.transform==affine and src.crs.to_epsg()==32617
            np.testing.assert_allclose(src.read(1),z,equal_nan=True)

def test_categorical_classes():
    values=np.array([[0.,22.5,90.,359.,np.nan]])
    classes,labels,_=classification(values,"aspect_map")
    assert classes.tolist()==[[0,1,2,0,-1]]
    assert labels[2]=="E"
    classes,_,_=classification(np.array([[-1.,0.,1.,np.nan]]),"cutfill_map")
    assert classes.tolist()==[[0,1,2,-1]]

def test_flat_aspect_and_watershed_share_receiver_graph():
    from terrain.advanced import _watershed
    z=np.array([[7.,7.,7.],[8.,8.,6.],[9.,5.,4.]])
    valid=np.ones_like(z,bool)
    _,_,accum=d8_flow(z,valid,10,10)
    for r in range(3):
        for c in range(3):
            basin=_watershed(z,valid,(r,c),from_origin(0,30,10,10))
            assert basin.sum()==accum[r,c]
    classes,labels,_=classification(np.array([[-1.,np.nan,22.5]]),"aspect_map")
    assert labels[-1]=="Flat" and classes.tolist()==[[8,-1,1]]

def test_circular_mean_wraps_north_and_omits_ambiguous_opposites():
    from terrain.professional import circular_mean_degrees
    assert circular_mean_degrees([359,1])==pytest.approx(0)
    assert circular_mean_degrees([0,180]) is None
    assert circular_mean_degrees([]) is None
