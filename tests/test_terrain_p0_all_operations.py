"""P0 end-to-end analytical oracles for EVERY public Terrain operation.

The reference DEM is derived from a known planar equation z(r,c)=100+c, with
10 m cells in a low-distortion UTM CRS. Expected values are derived analytically
without calling GeoFathom algorithms to compute the expected answer.

Separate zero-relief data exercise unrestricted viewsheds and shortest routing.
This is implementation conformance on controlled data, not field-survey
accuracy certification or a substitute for real terrain case studies.
"""
import base64
import math

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from terrain.advanced import run_terrain
from terrain.catalog import CORE_OPERATIONS
from terrain.engine import analyze_area, elevation_profile


UTM_TO_GEO=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
TRANSFORM=from_origin(500000,4500000,10,10)
ALL_OPERATIONS=tuple(sorted(CORE_OPERATIONS))
PLANE=np.tile(100+np.arange(24,dtype=np.float32),(24,1))
# R/C indices 2..21 inclusive. Polygon boundaries are intentionally
# between pixel centers and away from integer-grid roundoff.
SELECTED=PLANE[2:22,2:22]
CELL_AREA=100
N=400


def wgs(x,y):
    return list(UTM_TO_GEO.transform(x,y))


def center(row,col):
    return wgs(500005+10*col,4499995-10*row)


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    base=tmp_path_factory.mktemp("terrain-p0-oracles")
    paths={}
    for name,data in [("plane",PLANE),("flat",np.full_like(PLANE,200.)),
                      ("reference",PLANE-3.)]:
        file=base/f"{name}.tif"
        with rasterio.open(file,"w",driver="GTiff",width=24,height=24,
                           count=1,dtype="float32",crs="EPSG:32617",
                           transform=TRANSFORM,nodata=-9999) as writer:
            writer.write(data,1)
            writer.update_tags(VERTICAL_DATUM="NAVD88",VERTICAL_UNIT="m")
        paths[name]=file
    ring=[wgs(500021,4499979),wgs(500219,4499979),
          wgs(500219,4499781),wgs(500021,4499781),
          wgs(500021,4499979)]
    paths["polygon"]={"type":"Polygon","coordinates":[ring]}
    paths["line"]={"type":"LineString","coordinates":[
        wgs(500065,4499905),wgs(500165,4499905)]}
    return paths


def float_raster(result):
    data=result["raster"]
    with MemoryFile(base64.b64decode(data["geotiff"])) as memory:
        with memory.open() as src:
            assert src.crs.to_epsg()==32617
            assert src.transform.a==10
            array=src.read(1).astype(float)
            assert int(np.isfinite(array).sum())==data["valid_cells"]
            assert sum(item["cells"] for item in data["legend"])==data["valid_cells"]
            return array


@pytest.mark.parametrize("operation",ALL_OPERATIONS,ids=ALL_OPERATIONS)
def test_p0_operation(operation,study):
    """Each of the 28 operations must match an independently known outcome."""
    path=study["plane"]
    area=study["polygon"]
    if operation=="slope":
        result=analyze_area(path,area,gradient_method="zevenbergen_thorne")
        assert result["valid_pixels"]==N
        assert result["gradient_pixels"]==18*18
        assert result["mean_slope_deg"]==pytest.approx(math.degrees(math.atan(.1)),abs=.0001)
        assert result["mean_aspect_deg"]==pytest.approx(270,abs=.01)
        return
    if operation=="profile":
        result=elevation_profile(path,study["line"],samples=11)
        assert len(result["samples"])==11
        actual=[p["elevation_m"] for p in result["samples"]]
        assert actual[0]==106 and actual[-1]==116
        assert all(a is not None and 106<=a<=116 for a in actual)
        assert result["length_m"]==pytest.approx(100,abs=.5)
        return
    kwargs={}
    if operation in ("visibility","viewshed_multi","least_cost"):
        path=study["flat"]
    if operation=="dem_difference":
        kwargs["comparison_path"]=study["reference"]
    if operation in ("volume","cutfill_map"):
        kwargs["reference"]=110
    if operation in ("streams","stream_order"):
        kwargs["stream_cells"]=2
    if operation=="watershed":
        kwargs["point"]=center(12,2)
    if operation=="visibility":
        kwargs.update(point=center(12,12),max_distance_m=50,
                      view_azimuth=0,view_width=90)
    if operation=="viewshed_multi":
        kwargs["observer_points"]=[center(8,8),center(16,16)]
    if operation=="least_cost":
        kwargs.update(point=center(12,3),end_point=center(12,13),
                      max_slope=30,route_model="distance")
    if operation=="suitability":
        kwargs.update(min_elevation=105,max_elevation=115,max_slope=10,
                      max_tri=10)
    if operation=="contours":
        kwargs["interval"]=5
    if operation=="cross_sections":
        kwargs.update(section_spacing=50,section_width=20)
        area=study["line"]
    if operation=="mesh":
        kwargs["mesh_samples"]=64
    result=run_terrain(path,area,operation,**kwargs)
    assert result["operation"]==operation
    assert result["metrics"],f"{operation} returned no physical metrics"
    if operation=="cross_sections":
        sections=result["sections"]
        assert len(sections)==3
        assert [s["samples"][20]["elevation_m"] for s in sections]==[106,111,116]
        assert result["valid_cells"]==123
        return
    assert result["valid_cells"]==N
    assert result["cell_area_m2"]==CELL_AREA
    quality=result["quality"]
    assert quality["source_overlap_pct"]==pytest.approx(100,abs=.01)
    assert quality["valid_study_cell_pct"]==pytest.approx(100)
    assert quality["reference_validation"]=="not_performed"
    assert quality["projection_max_scale_error_pct"]<1
    m=result["metrics"]
    if operation=="contours":
        from shapely.geometry import shape
        to_utm=Transformer.from_crs("EPSG:4326","EPSG:32617",always_xy=True)
        assert m["contour_levels"]==4
        assert {f["properties"]["elevation_m"] for f in result["features"]}=={105,110,115,120}
        for feature in result["features"]:
            level=feature["properties"]["elevation_m"]
            line=shape(feature["geometry"])
            pieces=(line.geoms if line.geom_type=="MultiLineString" else [line])
            for piece in pieces:
                for lon,lat in piece.coords:
                    xx,_=to_utm.transform(lon,lat)
                    assert xx==pytest.approx(500005+10*(level-100),abs=.005)
        return
    if operation=="distribution":
        assert sum(b["cells"] for b in result["distribution"])==N
        assert sum(b["area_m2"] for b in result["distribution"])==N*CELL_AREA
        assert result["distribution"][-1]["cumulative_pct"]==pytest.approx(100)
        assert m["mean_m"]==pytest.approx(111.5)
        assert m["median_m"]==pytest.approx(111.5)
        assert m["relief_m"]==pytest.approx(19)
        return
    if operation=="volume":
        cut=np.maximum(SELECTED-110,0).sum()*CELL_AREA
        fill=np.maximum(110-SELECTED,0).sum()*CELL_AREA
        assert m["cut_m3"]==pytest.approx(cut)
        assert m["fill_m3"]==pytest.approx(fill)
        assert m["net_cut_m3"]==pytest.approx(cut-fill)
        return
    if operation=="watershed":
        assert m["upstream_cells"]==20
        assert m["upstream_grid_area_m2"]==2000
        return
    if operation=="visibility":
        eligible=m["eligible_cells"]
        assert 0<eligible<N
        assert m["out_of_scope_cells"]==N-eligible
        assert m["visible_cells"]==eligible
        assert m["unknown_cells"]==0
        assert m["visibility_pct_of_known_eligible"]==pytest.approx(100)
        return
    if operation=="mesh":
        mesh=result["mesh"]
        assert mesh["rows"]==20 and mesh["cols"]==20
        assert mesh["heights"][0]==102
        assert mesh["heights"][-1]==121
        assert m["mesh_vertices"]==N
        assert m["mesh_sampling_step"]==1
        return
    data=float_raster(result)
    if operation=="elevation":
        np.testing.assert_allclose(data,SELECTED,atol=0)
    elif operation=="slope_map":
        np.testing.assert_allclose(data[1:-1,1:-1],
                                   math.degrees(math.atan(.1)),atol=.00002)
        assert np.isnan(data[0]).all()
    elif operation=="aspect_map":
        np.testing.assert_allclose(data[1:-1,1:-1],270,atol=.00002)
        assert np.isnan(data[0]).all()
    elif operation=="hillshade":
        beta=math.radians(45)
        az=math.radians(315)
        east=.1
        illumination=255*max(0,(math.sin(beta)-east*math.cos(beta)*math.sin(az))/
                             math.sqrt(1+east**2))
        assert data[10,10]==pytest.approx(illumination,abs=.0002)
    elif operation=="tri":
        assert data[10,10]==pytest.approx(math.sqrt(6),abs=.00001)
    elif operation=="tpi":
        assert data[10,10]==pytest.approx(0,abs=.00001)
    elif operation in ("curvature","plan_curvature","profile_curvature"):
        assert data[10,10]==pytest.approx(0,abs=1e-10)
    elif operation=="flow_direction":
        np.testing.assert_array_equal(data[:,1:],np.full((20,19),16))
        np.testing.assert_array_equal(data[:,0],np.zeros(20))
    elif operation=="flow_accumulation":
        np.testing.assert_allclose(data,np.tile(np.arange(20,0,-1),(20,1)))
    elif operation=="flow_accumulation_mfd":
        assert float(np.nansum(data[:,0]))==pytest.approx(N,rel=.00001)
        assert np.nanmin(data)==pytest.approx(1,abs=.0001)
    elif operation=="streams":
        assert m["stream_cells"]==N-20
        np.testing.assert_array_equal(data[:,:-1],np.ones((20,19)))
        np.testing.assert_array_equal(data[:,-1],np.zeros(20))
    elif operation=="stream_order":
        assert m["max_stream_order"]==1
        assert m["channel_cells"]==N-20
        np.testing.assert_array_equal(data[np.isfinite(data)],np.ones(N-20))
    elif operation=="viewshed_multi":
        assert m["visible_cells"]==N
        assert m["visible_by_all_cells"]==N
        np.testing.assert_array_equal(data,np.full((20,20),2))
    elif operation=="cutfill_map":
        np.testing.assert_allclose(data,SELECTED-110,atol=.00001)
        assert m["cut_m3"]==pytest.approx(np.maximum(SELECTED-110,0).sum()*CELL_AREA)
    elif operation=="suitability":
        assert m["suitable_area_m2"]==pytest.approx(18*11*CELL_AREA)
        assert m["product_valid_cells"]==18*18
        assert np.nansum(data)==18*11
    elif operation=="least_cost":
        assert m["route_length_m"]==pytest.approx(100,abs=.01)
        assert m["route_cost"]==pytest.approx(100,abs=.01)
        assert m["route_cells"]==11
        assert np.nansum(data)==11
    elif operation=="dem_difference":
        np.testing.assert_allclose(data,3,atol=.0001)
        assert m["net_elevation_volume_m3"]==pytest.approx(3*N*CELL_AREA)
        assert m["comparison_coverage_pct"]==pytest.approx(100)
    else:
        raise AssertionError(f"Missing independent P0 oracle: {operation}")


def test_p0_catalog_and_oracle_set_match_exactly():
    """A new operation cannot be added without a scientific acceptance oracle."""
    from terrain.catalog import GROUPS
    assert len(ALL_OPERATIONS)==28
    assert set(ALL_OPERATIONS)=={name for names in GROUPS.values() for name in names}
