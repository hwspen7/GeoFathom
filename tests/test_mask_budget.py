"""The polygonization preflight must count seams between read bands."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from imagery.raster import RasterError
from vision import tiled

def test_fragmentation_at_row_band_boundary(tmp_path,monkeypatch):
    path=tmp_path/"mask.tif"
    mask=np.zeros((256,64),np.uint8)
    mask[128:]=1
    with rasterio.open(path,"w",driver="GTiff",width=64,height=256,count=1,
            dtype="uint8",crs="EPSG:4326",transform=from_origin(10,30,.001,.001)) as ds:
        ds.write(mask,1)
    monkeypatch.setattr(tiled,"MAX_BOUNDARY_TRANSITIONS",63)
    with pytest.raises(RasterError,match="fragmented"):
        tiled._disk_features(path,{1:"object"})
