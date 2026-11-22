"""Numerical DEM fixtures for the new interactive terrain operations."""
import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import Transformer
import pytest
from terrain.advanced import run_terrain,_watershed,_visibility
from imagery.raster import RasterError

@pytest.fixture
def dem(tmp_path):
    path=tmp_path/"plane.tif"
    affine=from_origin(500000,4500000,10,10)
    z=np.tile(np.arange(20,dtype=np.float32)+100,(20,1))
    with rasterio.open(path,"w",driver="GTiff",width=20,height=20,count=1,
        dtype="float32",crs="EPSG:32617",transform=affine,nodata=-9999) as ds:ds.write(z,1)
    t=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    ring=[t.transform(x,y) for x,y in [(500020,4499980),(500180,4499980),(500180,4499820),(500020,4499820),(500020,4499980)]]
    return path,{"type":"Polygon","coordinates":[ring]}

def test_cut_fill_known_projected_cells(dem):
    path,polygon=dem
    result=run_terrain(path,polygon,"volume",reference=110)
    assert result["valid_cells"]==256
    assert result["metrics"]["cut_m3"]==pytest.approx(sum(range(1,8))*16*100)
    assert result["metrics"]["fill_m3"]==pytest.approx(sum(range(1,9))*16*100)

def test_contours_and_mesh_are_real_dem_outputs(dem):
    path,polygon=dem
    result=run_terrain(path,polygon,"contours",interval=5)
    assert {f["properties"]["elevation_m"] for f in result["features"]}=={105,110,115}
    assert all(f["geometry"]["type"]=="LineString" for f in result["features"])
    mesh=run_terrain(path,polygon,"mesh")["mesh"]
    assert len(mesh["heights"])==mesh["rows"]*mesh["cols"]
    assert min(v for v in mesh["heights"] if v is not None)==102

def test_d8_plane_flows_only_to_same_row_outlet():
    z=np.tile(np.arange(5,dtype=float),(5,1))
    mask=_watershed(z,np.ones_like(z,bool),(2,0),from_origin(0,50,10,10))
    assert mask.sum()==5 and mask[2].all()

def test_visibility_ridge_blocks_cells_beyond_it():
    z=np.zeros((5,5),float);z[:,2]=30
    visible,known=_visibility(z,np.ones_like(z,bool),(2,0),from_origin(0,50,10,10),1.7,0)
    assert known.all() and visible[2,1] and not visible[2,4]

def test_visibility_and_watershed_require_valid_origin(dem):
    path,polygon=dem
    with pytest.raises(RasterError,match="Observer/outlet"):
        run_terrain(path,polygon,"visibility",point=[0,0])


def test_contours_preserve_more_than_100_disconnected_paths():
    from shapely.geometry import box,shape
    from terrain.advanced import _contours
    # Same raster dimensions as a real 219x140, 30-m DEM acceptance case.
    # Isolated hills produce hundreds of legitimate contours at 10 m.
    z=np.full((140,219),100.0)
    z[3:-3:8,3:-3:8]=120.0
    affine=from_origin(500000,4500000,30,30)
    result=_contours(z,np.ones_like(z,bool),affine,"EPSG:32617",
        box(500000,4500000-140*30,500000+219*30,4500000),10)
    expected=len(range(3,137,8))*len(range(3,216,8))
    assert expected>100
    assert sum(f["properties"]["contour_path_count"] for f in result)==expected
    assert len(result)==1
    assert result[0]["geometry"]["type"]=="MultiLineString"
    assert len(shape(result[0]["geometry"]).geoms)==expected
    assert all(line.is_closed for line in shape(result[0]["geometry"]).geoms)


def test_long_contours_split_without_losing_segments():
    from shapely.geometry import LineString
    from terrain.advanced import _contour_groups
    line=LineString([(i,0) for i in range(25001)])
    groups=list(_contour_groups([line]))
    assert len(groups)==3
    assert all(len(g.coords)<=10000 for g in groups)
    assert sum(g.length for g in groups)==line.length
    assert all(a.coords[-1]==b.coords[0] for a,b in zip(groups,groups[1:]))


def test_visibility_over_128_and_exact_ray_parity():
    # A flat plane is fully visible from any cell; a masked path is unknown.
    affine=from_origin(0,1500,10,10)
    z=np.zeros((150,160),float)
    valid=np.ones_like(z,dtype=bool)
    seen,known=_visibility(z,valid,(75,80),affine,1.7,0.)
    assert seen.all() and known.all()
    valid[:,90]=False
    seen,known=_visibility(z,valid,(75,80),affine,1.7,0.)
    assert not known[75,100] and not seen[75,100] and seen[75,85]


def test_coverage_reports_partial_footprint(dem):
    path,_=dem
    convert=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    polygon={"type":"Polygon","coordinates":[[convert.transform(x,y) for x,y in
        [(499900,4500000),(500100,4500000),(500100,4499800),(499900,4499800),(499900,4500000)]]]}
    result=run_terrain(path,polygon,"volume",reference=105)
    assert result["metrics"]["dataset_overlap_pct"]==pytest.approx(50,abs=.01)
    assert result["metrics"]["valid_grid_pct"]==100
    assert "intersection only" in result["warning"]

def test_elevation_distribution_preserves_full_grid_and_area(dem):
    path,polygon=dem
    result=run_terrain(path,polygon,"distribution")
    bins=result["distribution"]
    assert sum(b["cells"] for b in bins)==result["valid_cells"]==256
    assert sum(b["area_m2"] for b in bins)==pytest.approx(25600)
    assert bins[-1]["cumulative_pct"]==100
    assert all(a["cumulative_pct"]<=b["cumulative_pct"] for a,b in zip(bins,bins[1:]))
    assert result["metrics"]["minimum_m"]==102
    assert result["metrics"]["maximum_m"]==117
    assert result["metrics"]["median_m"]==109.5
    assert result["metrics"]["hypsometric_integral"]==pytest.approx(.5)

def test_flat_distribution_excludes_nodata_and_avoids_division_by_zero(dem):
    path,polygon=dem
    with rasterio.open(path,"r+") as ds:
        z=np.full((20,20),42,dtype=np.float32)
        z[4,4]=-9999
        ds.write(z,1)
    result=run_terrain(path,polygon,"distribution")
    assert result["valid_cells"]==255 and result["missing_cells"]==1
    assert result["distribution"]==[{"lower_m":42.,"upper_m":42.,"cells":255,"area_m2":25500.,"cumulative_pct":100.}]
    assert result["metrics"]["stddev_m"]==0
    assert "hypsometric_integral" not in result["metrics"]

@pytest.mark.parametrize("operation",["elevation","slope_map","aspect_map","hillshade","tri","tpi","curvature","flow_direction","flow_accumulation","streams","suitability","cutfill_map"])
def test_professional_surface_products(dem,operation):
    path,polygon=dem
    result=run_terrain(path,polygon,operation,reference=110,stream_cells=2)
    assert result["operation"]==operation
    assert result["raster"]["valid_cells"]>0
    assert len(result["raster"]["corners"])==4
    assert sum(b["cells"] for b in result["raster"]["legend"])==result["raster"]["valid_cells"]
    if operation=="cutfill_map":
        assert result["metrics"]["cut_m3"]==pytest.approx(44800)
        assert result["metrics"]["fill_m3"]==pytest.approx(57600)

def test_least_cost_projected_route(dem):
    path,polygon=dem
    t=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    result=run_terrain(path,polygon,"least_cost",point=t.transform(500035,4499965),
                       end_point=t.transform(500145,4499855),max_slope=45)
    assert result["metrics"]["route_length_m"]>0
    assert result["features"][0]["geometry"]["type"]=="LineString"

def test_cross_sections_and_rgb_texture(dem,tmp_path):
    path,polygon=dem
    t=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    line={"type":"LineString","coordinates":[t.transform(500050,4499950),t.transform(500150,4499850)]}
    result=run_terrain(path,line,"cross_sections",section_spacing=50,section_width=10)
    assert len(result["sections"])==4 and result["valid_cells"]>0
    assert result["sections"][0]["samples"][20]["offset_m"]==0
    rgb=tmp_path/"rgb.tif"
    with rasterio.open(rgb,"w",driver="GTiff",width=20,height=20,count=3,dtype="uint8",
                       crs="EPSG:32617",transform=from_origin(500000,4500000,10,10)) as ds:
        ds.write(np.full((3,20,20),128,dtype=np.uint8))
    mesh=run_terrain(path,polygon,"mesh",texture_path=rgb)["mesh"]
    assert mesh["texture"]["coverage_pct"]==pytest.approx(100)
    assert mesh["texture"]["png"].startswith("data:image/png;base64,")

def test_flat_aspect_and_out_of_bounds_profile(dem):
    from terrain.engine import elevation_profile
    path,polygon=dem
    with rasterio.open(path,"r+") as ds:ds.write(np.full((20,20),42,dtype=np.float32),1)
    result=run_terrain(path,polygon,"aspect_map")
    assert result["metrics"]["directional_cells"]==0
    assert result["metrics"]["flat_cells"]>0
    t=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    line={"type":"LineString","coordinates":[t.transform(499900,4499900),t.transform(500100,4499900)]}
    samples=elevation_profile(path,line,10)["samples"]
    assert samples[0]["elevation_m"] is None and samples[-1]["elevation_m"]==42


def test_slope_product_handles_over_one_million_pixels_end_to_end(tmp_path):
    # Regression: downloading a larger DEM is not useful if its normal slope
    # operation still refuses the historical 1024x1024 analysis window.
    from pyproj import Transformer
    side=1040
    cell_m=10
    west,north=500000,4500000
    path=tmp_path/"large-flat-terrain.tif"
    affine=from_origin(west,north,cell_m,cell_m)
    with rasterio.open(path,"w",driver="GTiff",width=side,height=side,count=1,
                       dtype="float32",crs="EPSG:32617",transform=affine,
                       nodata=-9999,compress="deflate") as target:
        target.write(np.full((side,side),220,dtype=np.float32),1)
    conv=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    margin=4
    coords=[(west+margin,north-margin),
            (west+side*cell_m-margin,north-margin),
            (west+side*cell_m-margin,north-side*cell_m+margin),
            (west+margin,north-side*cell_m+margin),
            (west+margin,north-margin)]
    polygon={"type":"Polygon","coordinates":[[conv.transform(x,y) for x,y in coords]]}
    result=run_terrain(path,polygon,"slope_map")
    assert result["valid_cells"]>1_000_000
    assert result["raster"]["valid_cells"]>1_000_000
    assert result["metrics"]["product_max"]==pytest.approx(0,abs=1e-6)
    assert result["raster"]["width"]>=1024
