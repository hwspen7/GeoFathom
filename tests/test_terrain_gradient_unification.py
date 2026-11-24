"""Small/tiled slope summaries and raster derivatives use identical selectable kernels."""
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.windows import Window
from terrain.engine import _native_slope
from terrain.tiled import analyze_area_tiled
from terrain.professional import derivatives
from imagery.raster import RasterError

@pytest.mark.parametrize("method",["horn","zevenbergen_thorne"])
def test_slope_summary_matches_physical_surface_gradient(method):
    z=np.tile(np.arange(19,dtype=np.float32)*2,(19,1))
    valid=np.ones(z.shape,bool)
    summary=_native_slope(z,valid,10,10,gradient_method=method)
    raster=derivatives(z.astype(float),valid,10,10,gradient_method=method)
    assert summary["mean_slope_deg"]==pytest.approx(np.nanmean(raster["slope_map"]),abs=1e-5)
    assert summary["maximum_slope_deg"]==pytest.approx(np.nanmax(raster["slope_map"]),abs=1e-5)
    assert summary["mean_aspect_deg"]==pytest.approx(270)

def test_tiled_zt_matches_direct_surface_across_tile_halos():
    height,width=520,521
    y,x=np.indices((height,width))
    z=(0.04*x*x+0.2*y).astype(np.float32)
    with MemoryFile() as mem:
        with mem.open(driver="GTiff",height=height,width=width,count=1,
                      dtype="float32",crs="EPSG:32617",
                      transform=from_origin(500000,4500000,10,10),nodata=-9999) as dataset:
            dataset.write(z,1)
            from shapely.geometry import box,mapping
            tiled=analyze_area_tiled(dataset,mapping(box(*dataset.bounds)),
                Window(0,0,width,height),gradient_method="zevenbergen_thorne")
    direct=_native_slope(z,np.ones(z.shape,bool),10,10,"zevenbergen_thorne")
    assert tiled["mean_slope_deg"]==pytest.approx(direct["mean_slope_deg"],abs=1e-4)
    assert tiled["maximum_slope_deg"]==pytest.approx(direct["maximum_slope_deg"],abs=1e-4)
    assert tiled["gradient_pixels"]==direct["gradient_pixels"]

def test_invalid_gradient_is_rejected_without_fallback():
    with pytest.raises(RasterError,match="gradient method"):
        _native_slope(np.ones((5,5)),np.ones((5,5),bool),1,1,"invented")
