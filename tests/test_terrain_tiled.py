"""Streaming Horn slope acceptance: exact tile halos and bounded reads."""
from threading import Event

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
from rasterio.warp import transform_geom
from shapely.geometry import box, mapping

from terrain.engine import analyze_area, _native_slope
from terrain.tiled import analyze_area_tiled
from terrain.cancellation import TerrainCancelled


def _raster(path, data):
    grid=from_origin(500000,4500000,10,10)
    with rasterio.open(path,'w',driver='GTiff',width=data.shape[1],
                       height=data.shape[0],count=1,dtype='float32',
                       crs='EPSG:32617',transform=grid,nodata=-9999) as ds:
        ds.write(data.astype('float32'),1)
    return grid


def _full_polygon(src):
    # Use a padded footprint, so every source pixel is unambiguously covered.
    extent=box(src.bounds.left-100,src.bounds.bottom-100,
               src.bounds.right+100,src.bounds.top+100)
    return transform_geom(src.crs,'EPSG:4326',mapping(extent))


def test_tiled_horn_matches_full_grid_including_nodata_crossing_seams(tmp_path,monkeypatch):
    rng=np.random.default_rng(17)
    yy,xx=np.mgrid[0:19,0:23]
    values=100+xx*1.7+yy*.9+rng.random((19,23))*.05
    values[7:10,8:12]=-9999
    path=tmp_path/'terrain.tif'
    _raster(path,values)
    with rasterio.open(path) as src:
        polygon=transform_geom('EPSG:4326',src.crs,_full_polygon(src))
        raw=src.read(1,masked=True)
        heights=np.asarray(raw.filled(np.nan),dtype=np.float32)
        valid=np.isfinite(heights)&~np.ma.getmaskarray(raw)
        reference=_native_slope(heights,valid,10.,10.)
        # Small tiles force many interior block boundaries and 3x3 halos.
        import terrain.tiled as module
        monkeypatch.setattr(module,'_BLOCK',5)
        result=analyze_area_tiled(src,polygon,Window(0,0,src.width,src.height))
        assert result['valid_pixels']==int(valid.sum())
        assert result['gradient_pixels']==reference['gradient_pixels']
        assert result['mean_slope_deg']==pytest.approx(reference['mean_slope_deg'],abs=0.002)
        assert result['maximum_slope_deg']==pytest.approx(reference['maximum_slope_deg'],abs=0.002)
        assert result['elevation_mean_m']==pytest.approx(float(heights[valid].mean()),abs=0.002)


def test_wide_study_window_uses_streaming_engine(tmp_path):
    # Forces the large-area path using a thin but >4096-column GeoTIFF.
    rows,cols=6,4101
    data=np.tile(np.arange(cols,dtype=np.float32)*10,(rows,1))
    path=tmp_path/'wide.tif'
    _raster(path,data)
    with rasterio.open(path) as src:
        geo=_full_polygon(src)
    summary=analyze_area(path,geo)
    assert summary['engine']=='numpy-tiled-horn'
    assert summary['gradient_pixels']>10000
    assert summary['mean_slope_deg']==pytest.approx(45.,abs=0.01)
    assert summary['maximum_slope_deg']==pytest.approx(45.,abs=0.01)


def test_tiled_horn_observes_cancellation(tmp_path):
    path=tmp_path/'small.tif'
    _raster(path,np.ones((12,12),dtype=np.float32))
    cancel=Event()
    cancel.set()
    with rasterio.open(path) as src:
        with pytest.raises(TerrainCancelled):
            analyze_area_tiled(src,transform_geom('EPSG:4326',src.crs,_full_polygon(src)),
                               Window(0,0,src.width,src.height),cancel)
