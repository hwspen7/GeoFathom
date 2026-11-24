"""Additional scientific/error-path coverage for the real Terrain engine.

These tests check documented physical invariants. They do not replace
backend computation with a stub or change the coverage configuration.
"""
import math

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import GeometryCollection, LineString, Polygon, box

from imagery.raster import RasterError
from terrain import advanced
from terrain.cancellation import TerrainCancelled


@pytest.fixture
def sources(tmp_path):
    transform=from_origin(500000,4500000,10,10)
    elevation=np.full((14,14),30,dtype=np.float32)
    elevation[1:-1,1:-1]=20
    elevation[7,7]=5
    elevation[0,0]=-9999
    primary=tmp_path/"primary.tif"
    reference=tmp_path/"reference.tif"
    for path,data in ((primary,elevation),(reference,np.where(elevation==-9999,-9999,elevation-2))):
        with rasterio.open(path,"w",driver="GTiff",width=14,height=14,count=1,
                           dtype="float32",crs="EPSG:32617",transform=transform,
                           nodata=-9999) as dest:
            dest.write(data,1)
            dest.update_tags(VERTICAL_DATUM="NAVD88")
    transformer=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    ring=[transformer.transform(x,y) for x,y in [
        (500010,4499990),(500130,4499990),(500130,4499870),
        (500010,4499870),(500010,4499990)]]
    origin=list(transformer.transform(500075,4499925))
    return primary,reference,{"type":"Polygon","coordinates":[ring]},origin


def test_hydrology_conditions_working_dem_and_preserves_original_dem(sources):
    path,_,polygon,origin=sources
    with rasterio.open(path) as source:
        before=source.read(1).copy()
    watershed=advanced.run_terrain(path,polygon,"watershed",
                                  point=origin,fill_sinks=True)
    assert watershed["metrics"]["upstream_cells"]>=1
    assert "flat_routing_cells" in watershed["metrics"]
    assert "Priority-flood" in watershed["warning"]
    assert watershed["metrics"]["conditioning_fill_volume_m3"]>=0
    assert watershed["features"]
    flow=advanced.run_terrain(path,polygon,"flow_accumulation",fill_sinks=True)
    assert flow["raster"]["valid_cells"]>0
    assert flow["metrics"]["conditioned_cells"]>=0
    with rasterio.open(path) as source:
        np.testing.assert_array_equal(source.read(1),before)


def test_visibility_with_curvature_has_spatial_result_and_metadata(sources):
    path,_,polygon,origin=sources
    result=advanced.run_terrain(path,polygon,"visibility",point=origin,
                                observer_height=1.7,target_height=0.2,
                                consider_curvature=True,refraction_coeff=0.1)
    assert result["metrics"]["visible_cells"]>=1
    assert result["metrics"]["unknown_cells"]>=0
    assert result["features"]
    assert "atmospheric refraction" in result["warning"]


def test_dem_difference_declared_vertical_datum_and_signed_mean(sources):
    path,reference,polygon,_=sources
    result=advanced.run_terrain(path,polygon,"dem_difference",comparison_path=reference)
    assert result["metrics"]["datum_labels_match"]==1
    assert result["metrics"]["elevation_change_mean_m"]==pytest.approx(2,abs=1e-5)
    assert result["metrics"]["comparison_cells"]>0
    assert "independently verified" in result["warning"]


@pytest.mark.parametrize("point,reason",[
    (None,"longitude and latitude"),
    ([True,40],"Invalid WGS84"),
    ([float('nan'),40],"Invalid WGS84"),
    ([-190,40],"Invalid WGS84"),
    ([0,0],"valid selected DEM cell"),
])
def test_projected_terrain_origin_validation(sources,point,reason):
    path,_,polygon,_=sources
    with pytest.raises(RasterError,match=reason):
        advanced.run_terrain(path,polygon,"watershed",point=point)


@pytest.mark.parametrize("height,target,curvature,k",[
    (-1,0,False,.13),(1,1001,False,.13),
    (1,0,True,-.01),(1,0,True,.51),
])
def test_visibility_rejects_nonphysical_height_and_refraction(height,target,curvature,k):
    elev=np.ones((6,6))
    valid=np.ones_like(elev,dtype=bool)
    with pytest.raises(RasterError):
        advanced._visibility(elev,valid,(2,2),from_origin(0,60,10,10),
                             height,target,consider_curvature=curvature,
                             refraction_coeff=k)


def test_visibility_enforces_extent_and_ray_budget(monkeypatch):
    z=np.zeros((3,3),dtype=float);valid=np.ones_like(z,bool)
    with pytest.raises(RasterError,match="10 km"):
        advanced._visibility(z,valid,(1,1),from_origin(0,20000,11000,11000),1,0)
    # Exceed the global ray budget before constructing any large ray matrices.
    dense=np.ones((600,600),dtype=bool)
    with pytest.raises(RasterError,match="100 million"):
        advanced._visibility(np.zeros_like(dense,float),dense,(0,0),
                             from_origin(0,600,1,1),1,0)


def test_contour_budget_and_invalid_intervals_are_explicit(sources,monkeypatch):
    path,_,polygon,_=sources
    for invalid in (0,-1,math.nan,math.inf):
        with pytest.raises(RasterError,match="positive finite"):
            advanced.run_terrain(path,polygon,"contours",interval=invalid)
    with pytest.raises(RasterError,match="larger interval"):
        advanced.run_terrain(path,polygon,"contours",interval=0.05)
    # Reject too-dense geometry instead of silently omitting contours.
    monkeypatch.setattr(advanced,"_CONTOUR_VERTEX_BUDGET",0)
    with pytest.raises(RasterError,match="budget|vertices"):
        advanced.run_terrain(path,polygon,"contours",interval=2)


def test_mask_vectorization_keeps_tiles_and_holes_and_bounds_vertices():
    valid=np.zeros((140,140),dtype=bool)
    valid[2:70,2:70]=True
    valid[6:10,6:10]=False
    valid[75:134,80:120]=True
    shapes=advanced._mask_features(valid,from_origin(500000,4500000,10,10),
                                   "EPSG:32617","Watershed mask")
    assert len(shapes)>=3
    assert all(feature["geometry"]["type"] in ("Polygon","MultiPolygon")
               for feature in shapes)
    assert all(feature["properties"]["source_type"]=="dem_derived"
               for feature in shapes)
    assert advanced._mask_features(np.zeros_like(valid),from_origin(0,10,1,1),
                                  "EPSG:32617","Empty")==[]


def test_polygon_parts_handles_geometry_collection_without_empty_parts():
    geom=GeometryCollection([Polygon(),LineString([(0,0),(1,1)]),
                             box(0,0,1,1)])
    parts=list(advanced._polygon_parts(geom))
    assert len(parts)==1
    assert parts[0].area==pytest.approx(1)


def test_terrain_operations_reject_unsupported_shape_and_budget(sources):
    path,_,polygon,_=sources
    with pytest.raises(RasterError,match="Unknown terrain operation"):
        advanced.run_terrain(path,polygon,"made_up_operation")
    with pytest.raises(RasterError,match="polygon study area"):
        advanced.run_terrain(path,{"type":"LineString",
                            "coordinates":polygon["coordinates"][0][:2]},"volume")
    with pytest.raises(RasterError,match="finite"):
        advanced.run_terrain(path,polygon,"volume",reference=math.nan)
