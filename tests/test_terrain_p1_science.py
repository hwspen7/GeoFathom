"""P1 terrain scientific acceptance: independent analytic arrays and real GeoTIFF API."""
import base64
from threading import Event

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from imagery.raster import RasterError
from terrain.advanced import run_terrain
from terrain.cancellation import TerrainCancelled
from terrain.p1_science import (
    dinfinity_accumulation, quadratic_curvature, design_surface,
    greedy_coverage, mesh_lod_tiles, breach_depressions, weighted_suitability,
)


def test_dinfinity_cardinal_plane_conserves_water_and_injected_external_area():
    z=np.tile(np.arange(6.,0.,-1.),(5,1))
    valid=np.ones(z.shape,bool)
    acc,angle=dinfinity_accumulation(z,valid,10,20)
    np.testing.assert_allclose(acc,np.tile(np.arange(1.,7.),(5,1)),atol=1e-12)
    np.testing.assert_allclose(angle[:,:-1],0,atol=1e-12)
    assert np.isnan(angle[:,-1]).all()
    external=np.zeros_like(z);external[2,0]=14
    out,_=dinfinity_accumulation(z,valid,10,20,external)
    assert out[2,-1]==pytest.approx(20.,abs=1e-10)
    assert float(acc[:,-1].sum())==pytest.approx(valid.sum())


def test_dinfinity_strict_nodata_corner_and_invalid_upstream_sources():
    z=np.array([[10.,np.nan],[np.nan,0.]])
    valid=np.array([[True,False],[False,True]])
    acc,angle=dinfinity_accumulation(z,valid,1,1)
    assert acc[0,0]==acc[1,1]==1
    assert np.isnan(acc[0,1]) and np.isnan(angle[0,0])
    with pytest.raises(RasterError,match="External inflow"):
        dinfinity_accumulation(z,valid,1,1,np.ones_like(z))
    with pytest.raises(RasterError,match="positive"):
        dinfinity_accumulation(z,valid,0,1)
    with pytest.raises(RasterError,match="finite"):
        dinfinity_accumulation(np.full((3,3),np.inf),np.ones((3,3),bool),1,1)


def test_dinfinity_multiple_slopes_and_cancellation():
    rows,cols=np.indices((7,7))
    z=100.-rows-2*cols
    acc,angles=dinfinity_accumulation(z,np.ones_like(z,bool),2,2)
    assert np.isfinite(acc).all() and float(acc[-1,-1])==pytest.approx(49.)
    assert np.nanmin(angles)>=0 and np.nanmax(angles)<2*np.pi
    done=Event();done.set()
    with pytest.raises(TerrainCancelled):
        dinfinity_accumulation(z,np.ones_like(z,bool),2,2,cancel=done)


@pytest.mark.parametrize("radius",[1,2,3,4])
def test_quadratic_fitted_curvature_exact_analytic_surface(radius):
    y,x=np.mgrid[-12:13,-12:13]
    z=1000000.+.02*x*x+.03*y*y+.1*x-.2*y+.01*x*y
    valid=np.ones(z.shape,bool)
    curvature=quadratic_curvature(z,valid,1,1,radius,"curvature")
    # d2z/dx2 + d2z/dy2 = 0.04 + 0.06 = 0.10 / m.
    assert curvature[12,12]==pytest.approx(.1,abs=1e-8)
    assert np.isnan(curvature[:radius]).all()
    valid[12,13]=False
    curvature=quadratic_curvature(z,valid,1,1,radius,"curvature")
    assert np.isnan(curvature[12,12])


def test_quadratic_curvature_flats_undefined_and_parameters_rejected():
    z=np.ones((9,9))*100.
    valid=np.ones_like(z,bool)
    result=quadratic_curvature(z,valid,5,5,2,"curvature")
    assert result[4,4]==pytest.approx(0,abs=1e-12)
    with pytest.raises(RasterError,match="No complete"):
        quadratic_curvature(z,valid,5,5,2,"profile_curvature")
    with pytest.raises(RasterError,match="radius"):
        quadratic_curvature(z,valid,5,5,5,"curvature")


def test_design_grade_volume_uncertainty_and_nonmutation():
    z=np.ones((3,3))*100.
    copy=z.copy()
    valid=np.ones_like(z,bool)
    diff,metrics=design_surface(z,valid,2,2,100,.1,0.,sigma_z=.5,max_grade=.3)
    assert metrics["cut_m3"]==pytest.approx(2.4)
    assert metrics["fill_m3"]==pytest.approx(2.4)
    assert metrics["net_cut_m3"]==pytest.approx(0)
    assert metrics["net_volume_independent_sigma_m3"]==pytest.approx(6)
    assert metrics["net_volume_correlated_sigma_m3"]==pytest.approx(18)
    np.testing.assert_array_equal(z,copy)
    assert diff[1,1]==0
    with pytest.raises(RasterError,match="maximum grade"):
        design_surface(z,valid,2,2,100,.3,.3,max_grade=.3)


def test_greedy_coverage_maximizes_incremental_cells_and_excludes_unknown():
    a=np.array([[1,1,0],[0,0,0]],bool)
    b=np.array([[0,1,1],[0,0,0]],bool)
    c=np.array([[0,0,0],[1,1,0]],bool)
    known=np.ones((2,3),bool)
    chosen,gains,coverage=greedy_coverage([a,b,c],[known]*3,2)
    assert chosen==[0,2] and gains==[2,2]
    assert int(coverage.sum())==4
    with pytest.raises(RasterError,match="visible must imply known"):
        greedy_coverage([a],[np.zeros_like(a)],1)


def test_mesh_lod_tiles_have_exact_shared_vertices_and_nodata():
    z=np.arange(65*65,dtype=float).reshape(65,65)
    valid=np.ones_like(z,bool);valid[1,1]=False
    tiles=mesh_lod_tiles(z,valid,1,2,tile_cells=32,levels=(1,2,4))
    level1=[tile for tile in tiles if tile["lod_step"]==1]
    assert len(level1)==4 and len(tiles)==6
    north_west=next(tile for tile in level1 if tile["row_start"]==0 and tile["col_start"]==0)
    north_east=next(tile for tile in level1 if tile["row_start"]==0 and tile["col_start"]==32)
    assert north_west["col_indices"][-1]==north_east["col_indices"][0]==32
    assert north_west["row_indices"]==north_east["row_indices"]
    assert north_west["heights"][1*33+1] is None
    coarse=next(tile for tile in tiles if tile["lod_step"]==2)
    assert coarse["row_indices"][-1]==64 and coarse["col_indices"][-1]==64


def test_breach_is_bounded_deterministic_and_preserves_source():
    z=np.zeros((7,7),float)
    z[1:6,1:6]=5
    z[3,3]=1
    valid=np.ones_like(z,bool)
    result,report=breach_depressions(z,valid,1,1,max_cut_m=10)
    assert report["breached_pits"]>=1 and report["unresolved_pits"]==0
    assert report["breach_total_excavation_depth_m"]>0
    assert result[3,3]==1 and z[3,3]==1
    assert result.min()<=z.min()
    with pytest.raises(RasterError,match="maximum excavation"):
        breach_depressions(z,valid,1,1,max_cut_m=0)


@pytest.fixture
def real_dem(tmp_path):
    z=(120.+.2*np.indices((25,25))[1]).astype(np.float32)
    affine=from_origin(500000,4500000,10,10)
    path=tmp_path/"p1-dem.tif"
    with rasterio.open(path,"w",driver="GTiff",height=25,width=25,count=1,
         crs="EPSG:32617",transform=affine,nodata=-9999,dtype="float32") as dst:
        dst.write(z,1)
    converter=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    corners=[(500020,4499980),(500230,4499980),(500230,4499770),
             (500020,4499770),(500020,4499980)]
    polygon={"type":"Polygon","coordinates":[[converter.transform(*p) for p in corners]]}
    observers=[converter.transform(500045,4499955),
               converter.transform(500205,4499795),
               converter.transform(500045,4499795)]
    return path,polygon,observers,affine,z


def test_real_geotiff_dinfinity_curvature_grade_and_lod(real_dem):
    path,polygon,_,_,_=real_dem
    hydro=run_terrain(path,polygon,"flow_accumulation",flow_routing_method="dinf")
    assert hydro["algorithm_options"]["flow_routing_method"]=="dinf"
    assert hydro["raster"]["unit"]=="cells"
    assert hydro["metrics"]["product_max"]>=2
    curvature=run_terrain(path,polygon,"curvature",curvature_method="quadratic",curvature_radius=3)
    assert curvature["algorithm_options"]["curvature_radius_cells"]==3
    assert abs(curvature["metrics"]["product_mean"])<1e-5
    volume=run_terrain(path,polygon,"volume",reference=120,
        design_east_grade=.01,design_north_grade=0.,elevation_sigma_m=.5)
    assert volume["metrics"]["net_volume_independent_sigma_m3"]>0
    mesh=run_terrain(path,polygon,"mesh",mesh_lod=True)
    assert mesh["mesh"]["lod"]["transport"]=="in_response_not_streamed"
    assert mesh["metrics"]["mesh_lod_tile_count"]>0
    with MemoryFile(base64.b64decode(curvature["raster"]["geotiff"])) as memory:
        with memory.open() as source:
            assert source.tags()["TERRAIN_OPERATION"]=="curvature"
            assert source.nodata!=source.nodata # nan nodata


def test_real_dsm_obstructions_and_greedy_multi_site_selection(real_dem,tmp_path):
    path,polygon,points,affine,z=real_dem
    baseline=run_terrain(path,polygon,"visibility",point=points[0])
    dsm_path=tmp_path/"p1-dsm.tif"
    dsm=z.copy();dsm[:,10]=1000
    with rasterio.open(dsm_path,"w",driver="GTiff",width=25,height=25,count=1,
         crs="EPSG:32617",transform=affine,dtype="float32",nodata=-9999) as dst:
        dst.write(dsm,1)
    obstructed=run_terrain(path,polygon,"visibility",point=points[0],dsm_path=dsm_path)
    assert obstructed["metrics"]["visible_cells"]<baseline["metrics"]["visible_cells"]
    assert obstructed["algorithm_options"]["dsm_source"] is True
    chosen=run_terrain(path,polygon,"viewshed_multi",observer_points=points,
        optimize_observers=2,dsm_path=dsm_path)
    assert chosen["metrics"]["observer_count"]==2
    assert chosen["metrics"]["candidate_site_count"]==3
    assert len(chosen["selection"]["selected_candidate_indices"])==2
    assert chosen["metrics"]["visible_cells"]>0
    assert "greedy_coverage_not_global_optimum" in chosen["quality"]["flags"]



def test_weighted_suitability_is_quantitative_and_respects_hard_constraints():
    z=np.array([[100.,125.],[150.,175.]])
    slope=np.array([[0.,10.],[0.,0.]])
    tri=np.array([[0.,0.],[0.,0.]])
    valid=np.ones((2,2),bool)
    score,metrics=weighted_suitability(z,valid,slope,tri,20,100,150,10,(2,1,1),sigma_z=1)
    assert score[0,0]==pytest.approx(.75)
    assert score[0,1]==pytest.approx(.75)
    assert score[1,0]==pytest.approx(.75)
    assert score[1,1]==0 # hard elevation bound
    assert metrics["suitable_pct"]==pytest.approx(75)
    assert metrics["score_weight_slope"]==pytest.approx(.5)
    assert 0<metrics["weighted_score_uncertainty_bound"]<1
    with pytest.raises(RasterError,match="weights"):
        weighted_suitability(z,valid,slope,tri,20,100,150,10,(0,0,0))


def test_weighted_suitability_real_tiff_preserves_utility_not_binary(real_dem):
    path,polygon,_,_,_=real_dem
    result=run_terrain(path,polygon,"suitability",
        max_slope=30,min_elevation=100,max_elevation=145,max_tri=50,
        suitability_model="weighted",suitability_weights=(2,1,1))
    assert result["raster"]["unit"]=="score_0_to_1"
    assert result["metrics"]["suitability_model_weighted"]==1
    with MemoryFile(base64.b64decode(result["raster"]["geotiff"])) as memory:
        with memory.open() as src:
            scores=src.read(1)
            assert src.tags()["TERRAIN_UNIT"]=="score_0_to_1"
            finite=scores[np.isfinite(scores)]
            assert len(np.unique(finite))>2
            assert np.min(finite)>=0 and np.max(finite)<=1
    assert result["algorithm_options"]["suitability_weights"]==[2,1,1]


def test_weighted_suitability_legacy_binary_classification_unchanged(real_dem):
    path,polygon,_,_,_=real_dem
    binary=run_terrain(path,polygon,"suitability",
        max_slope=30,min_elevation=100,max_elevation=145,max_tri=50)
    assert binary["raster"]["unit"]=="binary"
    assert len(binary["raster"]["legend"])==2



def test_external_upstream_inflow_is_explicit_grid_aligned_and_unit_checked(real_dem,tmp_path):
    path,polygon,_,affine,z=real_dem
    inlet=np.zeros(z.shape,dtype=np.float32)
    inlet[10,20]=12
    source=tmp_path/"known-inlet.tif"
    with rasterio.open(source,"w",driver="GTiff",height=25,width=25,count=1,
         crs="EPSG:32617",transform=affine,dtype="float32",nodata=-9999) as dst:
        dst.write(inlet,1)
        dst.update_tags(TERRAIN_UNIT="cell_equivalents")
    result=run_terrain(path,polygon,"flow_accumulation",flow_routing_method="dinf",
        external_inflow_path=source)
    assert result["metrics"]["external_inflow_total_cell_equivalents"]==pytest.approx(12)
    assert "external_upstream_contribution_input_unverified" in result["quality"]["flags"]
    assert result["algorithm_options"]["external_inflow_supplied"] is True
    with rasterio.open(source,"r+") as dst:
        dst.update_tags(TERRAIN_UNIT="m")
    with pytest.raises(RasterError,match="TERRAIN_UNIT"):
        run_terrain(path,polygon,"flow_accumulation",flow_routing_method="dinf",
            external_inflow_path=source)
    with pytest.raises(RasterError,match="only for D-infinity"):
        run_terrain(path,polygon,"flow_accumulation",flow_routing_method="d8",
            external_inflow_path=source)



def test_dinfinity_routes_to_single_valid_cardinal_neighbour_without_corner_cutting():
    z=np.array([[np.nan,9.,np.nan],[np.nan,8.,np.nan],[np.nan,7.,np.nan]])
    valid=np.isfinite(z)
    acc,angle=dinfinity_accumulation(z,valid,1,1)
    assert acc[2,1]==pytest.approx(3)
    assert np.isnan(acc[2,0]) and np.isnan(acc[2,2])
    assert angle[0,1]==pytest.approx(3*np.pi/2)


def test_greedy_coverage_retains_known_cell_when_unselected_candidate_is_unknown():
    first=np.array([[1,1,1]],bool)
    first_known=np.ones((1,3),bool)
    second=np.array([[0,0,0]],bool)
    second_known=np.zeros((1,3),bool)
    indices,gains,visible=greedy_coverage([first,second],[first_known,second_known],1)
    assert indices==[0] and gains==[3] and int(visible.sum())==3



def test_quadratic_engineering_surface_exact_volume_and_bounding_maximum_grade():
    z=np.full((5,5),100.)
    valid=np.ones_like(z,bool)
    diff,metrics=design_surface(z,valid,2.,2.,100.,
        max_grade=.1,curvature_east=.01,curvature_north=.02)
    assert metrics["cut_m3"]==pytest.approx(0,abs=1e-9)
    assert metrics["fill_m3"]==pytest.approx(12,abs=1e-9)
    assert metrics["design_bounding_max_grade"]==pytest.approx(np.hypot(.04,.08))
    assert diff[2,2]==0
    with pytest.raises(RasterError,match="maximum grade"):
        design_surface(z,valid,2.,2.,100.,max_grade=.08,
            curvature_east=.01,curvature_north=.02)
    valid[0,0]=False
    diff,metrics=design_surface(z,valid,2.,2.,100.,max_grade=.1,
        curvature_east=.01,curvature_north=.02)
    assert np.isnan(diff[0,0])
    assert metrics["fill_m3"]<12


def test_quadratic_design_is_exposed_in_cutfill_real_geotiff(real_dem):
    path,polygon,_,_,_=real_dem
    result=run_terrain(path,polygon,"cutfill_map",reference=120.,
        design_curvature_east=.00001,design_curvature_north=.00001,design_max_grade=.3)
    assert result["algorithm_options"]["design_curvature_east_per_m"]==pytest.approx(.00001)
    assert result["metrics"]["design_bounding_max_grade"]<=.3
    assert result["metrics"]["cut_m3"]>=0 and result["metrics"]["fill_m3"]>=0
