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


def test_directional_curvature_of_quadratic_surface():
    # Variation in x only has longitudinal curvature but zero plan curvature.
    z=np.tile(np.arange(7,dtype=float)**2,(7,1))
    valid=np.ones_like(z,bool)
    result=derivatives(z,valid,10,10)
    assert result["profile_curvature"][3,3]>0
    assert result["plan_curvature"][3,3]==pytest.approx(0,abs=1e-12)
    assert result["curvature"][3,3]==pytest.approx(0.02)
    assert np.isnan(result["profile_curvature"][0]).all()
    # Exactly flat terrain has no defined aspect or directional curvature.
    flat=derivatives(np.full((7,7),10.),valid,10,10)
    assert np.isnan(flat["plan_curvature"][3,3])
    assert np.isnan(flat["profile_curvature"][3,3])


def test_dem_difference_uses_zero_centered_diverging_legend():
    values=np.array([[-12.,-6.,-0.1,0.,0.1,6.,12.,np.nan]])
    classes,labels,colors=classification(values,'dem_difference')
    assert classes.tolist()==[[0,1,2,3,4,5,6,-1]]
    assert len(colors)==7 and labels[3]=='No change (0 m)'
    positive,_,_=classification(np.array([[2.,4.,8.]]),'dem_difference')
    negative,_,_=classification(np.array([[-2.,-4.,-8.]]),'dem_difference')
    assert np.all(positive>3) and np.all(negative<3)
    zero,_,_=classification(np.array([[0.,0.,np.nan]]),'dem_difference')
    assert zero.tolist()==[[3,3,-1]]


def test_least_cost_does_not_cut_through_either_nodata_corner():
    # Both side-neighbours are required for any diagonal move. The first
    # fixture would previously take an illegal diagonal shortcut.
    z=np.zeros((3,3),dtype=np.float64)
    valid=np.zeros_like(z,dtype=bool)
    valid[1,1]=valid[2,1]=valid[2,2]=True
    path,cost=least_cost(z,valid,(1,1),(2,2),1,1,45)
    assert path==[(1,1),(2,1),(2,2)]
    assert cost==pytest.approx(2)
    # Mirror the blocked side, and then block both orthogonal neighbours.
    valid=np.zeros_like(z,dtype=bool)
    valid[1,1]=valid[1,2]=valid[2,2]=True
    mirrored,cost=least_cost(z,valid,(1,1),(2,2),1,1,45)
    assert mirrored==[(1,1),(1,2),(2,2)]
    assert cost==pytest.approx(2)
    valid[1,2]=False
    with pytest.raises(RasterError,match="No valid terrain route"):
        least_cost(z,valid,(1,1),(2,2),1,1,45)


def test_least_cost_rejects_steep_diagonal_slope_even_if_flat_side_is_free():
    z=np.zeros((3,3))
    z[2,2]=100
    valid=np.ones_like(z,bool)
    with pytest.raises(RasterError,match="No valid terrain route"):
        least_cost(z,valid,(0,0),(2,2),1,1,10)


@pytest.mark.parametrize("operation,unit",[
    ("elevation","m"),("dem_difference","m"),("cutfill_map","m"),
    ("slope_map","degree"),("aspect_map","degree"),("hillshade","0..255"),
    ("tri","m"),("tpi","m"),("curvature","1/m"),
    ("plan_curvature","1/m"),("profile_curvature","1/m"),
    ("flow_direction","D8_code"),("flow_accumulation","cells"),
    ("streams","binary"),("suitability","binary"),("least_cost","binary"),
])
def test_derived_geotiff_value_units_are_not_mislabeled_as_elevation(operation,unit):
    data=np.array([[1.,2.],[3.,np.nan]],dtype=float)
    p=raster_product(data,operation,from_origin(500000,4500000,10,10),"EPSG:32617")
    assert p["unit"]==unit
    with MemoryFile(base64.b64decode(p["geotiff"])) as memory:
        with memory.open() as raster:
            assert raster.tags()["TERRAIN_UNIT"]==unit
            assert raster.tags()["TERRAIN_OPERATION"]==operation
            assert raster.tags()["TERRAIN_NODATA_POLICY"]=="NaN"
            assert np.isnan(raster.nodata)
            np.testing.assert_allclose(raster.read(1),data,equal_nan=True)


@pytest.mark.parametrize("operation",[
    "slope_map","aspect_map","hillshade","tri","tpi",
    "curvature","plan_curvature","profile_curvature","suitability",
])
def test_halo_tiled_derivatives_match_full_window_with_nodata(operation):
    from terrain.professional import _derived_surface_tiled
    yy,xx=np.indices((547,523),dtype=float)
    z=120+.1*yy+.2*xx+np.sin(yy/17)*10+np.cos(xx/19)*5
    valid=np.ones(z.shape,dtype=bool)
    valid[370:395,370:395]=False
    valid[380,:90]=False
    full=derivatives(z,valid,10,20)
    result,metrics=_derived_surface_tiled(
        z,valid,10,20,operation,
        max_slope=35,min_elevation=100,max_elevation=260,max_tri=20,
        azimuth=125,altitude=36,block=384)
    if operation=="hillshade":
        a,b=np.deg2rad([125,36])
        east,south=full["east"],full["south"]
        expected=255*np.clip((np.sin(b)-east*np.cos(b)*np.sin(a)
                            +south*np.cos(b)*np.cos(a))/
                            np.sqrt(1+east**2+south**2),0,1)
    elif operation=="suitability":
        good=np.isfinite(full["slope_map"])
        passed=(full["slope_map"]<=35)&(z>=100)&(z<=260)&(full["tri"]<=20)
        expected=np.where(good,passed.astype(float),np.nan)
        assert metrics["suitable_area_m2"]==pytest.approx(
            float((expected==1).sum()*200))
        assert metrics["suitable_pct"]==pytest.approx(
            float(100*(expected==1).sum()/good.sum()))
    elif operation=="aspect_map":
        expected=np.where(np.isfinite(full["slope_map"])&
                          ~np.isfinite(full["aspect_map"]),-1,full["aspect_map"])
    else:
        expected=full[operation]
    np.testing.assert_allclose(result,expected,rtol=0,atol=1e-10,equal_nan=True)
    assert np.isnan(result[0]).all() and np.isnan(result[:,-1]).all()
