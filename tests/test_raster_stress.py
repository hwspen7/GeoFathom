"""Scalable image smoke test and optional 8K hardware acceptance.

The 4K case runs in normal CI. Set GEOFATHOM_STRESS_8K=1 for the
8K acceptance case on a machine with sufficient disk and memory.
"""
import os
import time

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from vision.tiled import spectral_index_tiled


@pytest.mark.parametrize("width", [4096, 8192])
def test_full_resolution_4k_and_optional_8k(tmp_path,width):
    if width==8192 and os.getenv("GEOFATHOM_STRESS_8K")!="1":
        pytest.skip("Explicit opt-in required for resource-intensive 8K acceptance.")
    path=tmp_path / f"{width}.tif"
    height=width
    band=np.full((4,256,width),50,dtype=np.uint8)
    band[3]=200
    with rasterio.open(path,"w",driver="GTiff",width=width,height=height,
                       count=4,dtype="uint8",crs="EPSG:4326",
                       transform=from_origin(10,30,.000004,.000004),
                       compress="deflate",tiled=True,
                       blockxsize=256,blockysize=256) as dst:
        for row in range(0,height,256):
            dst.write(band,window=Window(0,row,width,256))
    started=time.perf_counter()
    result=spectral_index_tiled(
        path,f"{width}-image","ndvi",4,1,threshold=.4,
        tile_size=512,max_pixels=width*height,memory_mb=32)
    elapsed=time.perf_counter()-started
    assert result["pixel_grid"]==[width,height]
    assert result["valid_pixels"]==width*height
    assert result["classified_pixels"]==width*height
    assert result["tile_count"]==(width//512)**2
    assert len(result["features"])==1
    assert result["features"][0]["properties"]["pixel_count"]==width*height
    assert result["features"][0]["properties"]["area_m2"]>0
    assert result["features"][0]["properties"]["quality"]=="requires_user_review"
    print(f"Streaming {width}x{height}: {elapsed:.3f}s, "
          f"{width*height/max(elapsed,.001):.0f} px/s")
