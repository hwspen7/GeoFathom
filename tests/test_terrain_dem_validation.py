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
