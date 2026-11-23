"""Reference-grid DEM change analysis with real projected GeoTIFF fixtures."""
import base64
import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from imagery.raster import RasterError
from terrain.difference import compare_dem


def make_dem(path, values, affine):
    with rasterio.open(path, "w", driver="GTiff", height=values.shape[0],
                       width=values.shape[1], count=1, dtype="float32",
                       crs="EPSG:32617", transform=affine, nodata=-9999) as ds:
        ds.write(values.astype("float32"), 1)


def test_dem_difference_reprojects_and_preserves_nodata(tmp_path):
    affine=from_origin(500000,4500000,10,10)
    a=np.full((10,10),110.0)
    b=np.full((10,10),100.0)
    b[4,4]=-9999.0
    ref=tmp_path/"reference.tif"
    make_dem(ref,b,affine)
    preview,metrics=compare_dem(a,np.ones((10,10),bool),affine,"EPSG:32617",ref)
    assert metrics["comparison_cells"]==99
    assert metrics["comparison_coverage_pct"]==pytest.approx(99)
    assert metrics["elevation_change_mean_m"]==pytest.approx(10)
    assert metrics["elevation_change_rmse_m"]==pytest.approx(10)
    assert metrics["raised_volume_m3"]==pytest.approx(99000)
    assert metrics["lowered_volume_m3"]==0
    assert sum(b["cells"] for b in preview["legend"])==99
    with MemoryFile(base64.b64decode(preview["geotiff"])) as file:
        with file.open() as ds:
            values=ds.read(1)
            assert np.isnan(values[4,4])
            assert values[0,0]==pytest.approx(10)


def test_dem_difference_no_overlap_fails_without_fake_values(tmp_path):
    primary_affine=from_origin(500000,4500000,10,10)
    distant=from_origin(700000,4500000,10,10)
    ref=tmp_path/"distant.tif"
    make_dem(ref,np.full((5,5),100),distant)
    with pytest.raises(RasterError,match="no overlapping"):
        compare_dem(np.full((5,5),110),np.ones((5,5),bool),
                    primary_affine,"EPSG:32617",ref)


def test_dem_difference_needs_explicit_reference():
    with pytest.raises(RasterError,match="second DEM"):
        compare_dem(np.zeros((3,3)),np.ones((3,3),bool),
                    from_origin(0,30,10,10),"EPSG:32617",None)



def test_dem_difference_refuses_conflicting_declared_vertical_datums(tmp_path):
    affine=from_origin(500000,4500000,10,10)
    primary=tmp_path/'primary.tif'
    reference=tmp_path/'reference.tif'
    make_dem(primary,np.full((5,5),102.),affine)
    make_dem(reference,np.full((5,5),100.),affine)
    with rasterio.open(primary,'r+') as ds:ds.update_tags(VERTICAL_DATUM='NAVD88')
    with rasterio.open(reference,'r+') as ds:ds.update_tags(VERTICAL_DATUM='EGM96')
    with pytest.raises(RasterError,match='vertical datum mismatch'):
        compare_dem(np.full((5,5),102.),np.ones((5,5),bool),
                    affine,'EPSG:32617',reference,primary_path=primary)


def test_dem_difference_records_metadata_quality_and_signed_cells(tmp_path):
    affine=from_origin(500000,4500000,10,10)
    primary=tmp_path/'primary.tif'
    reference=tmp_path/'reference.tif'
    make_dem(primary,np.full((2,2),100.),affine)
    make_dem(reference,np.full((2,2),100.),affine)
    with rasterio.open(primary,'r+') as ds:ds.update_tags(VERTICAL_DATUM='NAVD88')
    with rasterio.open(reference,'r+') as ds:ds.update_tags(VERTICAL_DATUM='NAVD 88')
    values=np.array([[110.,90.],[100.,100.]])
    _,metrics=compare_dem(values,np.ones((2,2),bool),affine,'EPSG:32617',reference,primary_path=primary)
    assert metrics['datum_labels_match']==1
    assert metrics['increased_cells']==1
    assert metrics['decreased_cells']==1
    assert metrics['unchanged_cells']==2
    assert metrics['net_elevation_volume_m3']==pytest.approx(0)


def test_dem_difference_warning_exposes_partial_reference_coverage(tmp_path):
    from pyproj import Transformer
    from terrain.advanced import run_terrain
    affine=from_origin(500000,4500000,10,10)
    primary=tmp_path/"primary.tif"
    reference=tmp_path/"partial.tif"
    make_dem(primary,np.full((10,10),100.),affine)
    values=np.full((10,10),90.)
    values[:,5:]=-9999.
    make_dem(reference,values,affine)
    conv=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
    ring=[conv.transform(x,y) for x,y in [
        (500000,4500000),(500100,4500000),
        (500100,4499900),(500000,4499900),(500000,4500000)]]
    result=run_terrain(primary,{"type":"Polygon","coordinates":[ring]},
                       "dem_difference",comparison_path=reference)
    coverage=result["metrics"]["comparison_coverage_pct"]
    assert coverage==pytest.approx(50.,abs=1)
    assert f"{coverage:.1f}%" in result["warning"]
    assert "exclude uncovered cells" in result["warning"]


def test_exported_difference_raster_distinguishes_declared_datums(tmp_path):
    affine=from_origin(500000,4500000,10,10)
    primary=tmp_path/"primary.tif"
    reference=tmp_path/"reference.tif"
    make_dem(primary,np.full((5,5),102.),affine)
    make_dem(reference,np.full((5,5),100.),affine)
    for path in (primary,reference):
        with rasterio.open(path,"r+") as source:
            source.update_tags(VERTICAL_DATUM="NAVD88")
    product,metrics=compare_dem(np.full((5,5),102.),np.ones((5,5),bool),
                                affine,"EPSG:32617",reference,primary_path=primary)
    assert metrics["datum_labels_match"]==1
    with MemoryFile(base64.b64decode(product["geotiff"])) as memory:
        with memory.open() as raster:
            assert raster.tags()["TERRAIN_SOURCE_VERTICAL_DATUM"]=="NAVD88"
            assert raster.tags()["TERRAIN_REFERENCE_VERTICAL_DATUM"]=="NAVD88"
            assert raster.tags()["TERRAIN_UNIT"]=="m"
