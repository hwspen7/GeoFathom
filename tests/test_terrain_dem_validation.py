"""Reject silently scaled DEM bands before any terrain surface calculation."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from imagery.raster import RasterError
from terrain.engine import _check_dem


def test_scaled_dem_band_rejected(tmp_path):
    path=tmp_path/'scaled.tif'
    with rasterio.open(path,'w',driver='GTiff',count=1,height=5,width=5,
                       dtype='int16',crs='EPSG:32617',
                       transform=from_origin(500000,4500000,10,10)) as ds:
        ds.write(np.ones((5,5),dtype=np.int16),1)
        ds.scales=[0.01]
        ds.offsets=[0.]
    with rasterio.open(path) as src:
        with pytest.raises(RasterError,match='Scaled DEM bands'):
            _check_dem(src)


def test_unscaled_dem_stays_supported(tmp_path):
    path=tmp_path/'unscaled.tif'
    with rasterio.open(path,'w',driver='GTiff',count=1,height=5,width=5,
                       dtype='float32',crs='EPSG:32617',
                       transform=from_origin(500000,4500000,10,10)) as ds:
        ds.write(np.ones((5,5),dtype=np.float32),1)
    with rasterio.open(path) as src:
        _check_dem(src)


def test_conflicting_vertical_unit_tags_are_never_silently_overridden(tmp_path):
    path=tmp_path/"conflicting-units.tif"
    with rasterio.open(path,"w",driver="GTiff",count=1,height=5,width=5,
                       dtype="float32",crs="EPSG:32617",
                       transform=from_origin(500000,4500000,10,10)) as ds:
        ds.write(np.ones((5,5),dtype=np.float32),1)
        ds.set_band_unit(1,"m")
        ds.update_tags(VERTICAL_UNIT="foot")
    with rasterio.open(path) as src:
        with pytest.raises(RasterError,match="vertical units must be meters"):
            _check_dem(src)
    with rasterio.open(path,"r+") as ds:
        ds.update_tags(VERTICAL_UNIT="meters")
    with rasterio.open(path) as src:
        _check_dem(src)


def test_conflicting_vertical_datum_tags_fail_before_any_terrain_analysis(tmp_path):
    path=tmp_path/"conflicting-datums.tif"
    with rasterio.open(path,"w",driver="GTiff",count=1,height=5,width=5,
                       dtype="float32",crs="EPSG:32617",
                       transform=from_origin(500000,4500000,10,10)) as ds:
        ds.write(np.ones((5,5),dtype=np.float32),1)
        ds.update_tags(VERTICAL_DATUM="NAVD88",VERTICAL_REFERENCE="EGM96")
    with rasterio.open(path) as src:
        with pytest.raises(RasterError,match="Conflicting declared"):
            _check_dem(src)
    # Equivalent normalized spellings denote the same declared datum.
    with rasterio.open(path,"r+") as ds:
        ds.update_tags(VERTICAL_REFERENCE="NAVD 88")
    with rasterio.open(path) as src:
        _check_dem(src)


@pytest.mark.parametrize("derived_operation",["slope_map","aspect_map",
                                               "flow_accumulation","cutfill_map",
                                               "dem_difference"])
def test_derived_analytical_raster_cannot_be_reused_as_absolute_dem(derived_operation):
    import base64
    from rasterio.io import MemoryFile
    from terrain.professional import raster_product
    array=np.full((7,7),25.,dtype=np.float64)
    product=raster_product(array,derived_operation,
                           from_origin(500000,4500000,10,10),"EPSG:32617")
    with MemoryFile(base64.b64decode(product["geotiff"])) as memory:
        with memory.open() as source:
            with pytest.raises(RasterError,match="not source DEM elevations"):
                _check_dem(source)
    absolute=raster_product(array,"elevation",
                            from_origin(500000,4500000,10,10),"EPSG:32617")
    with MemoryFile(base64.b64decode(absolute["geotiff"])) as memory:
        with memory.open() as source:
            _check_dem(source)
