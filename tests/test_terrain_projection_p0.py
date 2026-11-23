"""P0 regression: projected meters must be representative of ground distance."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from imagery.raster import RasterError
from terrain.engine import _check_dem
from terrain.projection import grid_scale_error_percent


def _dem(path,crs,x,y):
    with rasterio.open(path,"w",driver="GTiff",count=1,height=16,width=16,
                       dtype="float32",nodata=-9999,
                       crs=crs,transform=from_origin(x,y,10,10)) as ds:
        ds.write(np.full((16,16),100,dtype="float32"),1)


def test_local_utm_distances_pass_scientific_projection_gate(tmp_path):
    path=tmp_path/"utm.tif"
    _dem(path,"EPSG:32617",500000,4500000)
    with rasterio.open(path) as src:
        _check_dem(src)
        error=grid_scale_error_percent(src)
        assert error<0.05


def test_high_latitude_web_mercator_is_rejected_as_quantitative_dem(tmp_path):
    path=tmp_path/"bad-metric-grid.tif"
    _dem(path,"EPSG:3857",100000,5500000)
    with rasterio.open(path) as src:
        with pytest.raises(RasterError,match="projection scale distortion"):
            _check_dem(src)
        with pytest.raises(RasterError,match="Web Mercator"):
            grid_scale_error_percent(src)
        

def test_low_latitude_web_mercator_only_passes_if_local_scale_meets_gate(tmp_path):
    path=tmp_path/"near-equator.tif"
    _dem(path,"EPSG:3857",0,100000)
    with rasterio.open(path) as src:
        assert 0<=grid_scale_error_percent(src)<2
        _check_dem(src)
