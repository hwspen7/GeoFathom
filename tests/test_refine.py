"""WGS84 geo-prompt projection and multi-click mask correction adapter."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from vision.refine import refine_raster
import vision.refine as ref


def test_refinement_projects_clicks_into_source_raster_pixels(monkeypatch,tmp_path):
    path=tmp_path/"sample.tif"
    rgb=np.zeros((3,64,64),dtype=np.uint8)
    transform=from_origin(120,32,.00001,.00001)
    with rasterio.open(path,"w",driver="GTiff",width=64,height=64,
                       count=3,dtype="uint8",crs="EPSG:4326",transform=transform) as dst:
        dst.write(rgb)
    requested={}
    def dummy(image,seed_x,seed_y,positive,negative,box):
        requested.update({"positive":positive,"negative":negative,"box":box})
        mask=np.zeros(image.shape[:2],dtype=np.uint8)
        mask[10:35,10:35]=1
        return mask,.8,"mock-sam"
    monkeypatch.setattr(ref,"sam_mask",dummy)
    def xy(x,y):return list(transform*(x,y))
    result=refine_raster(path,"test",xy(20,20),[xy(20,20)],
                         [xy(40,40)],[xy(10,10),xy(50,50)],64)
    assert result["confidence"]==pytest.approx(.8)
    assert requested["positive"][0]==pytest.approx([20,20])
    assert requested["negative"][0]==pytest.approx([40,40])
    assert requested["box"]==pytest.approx([10,10,50,50])
    assert result["measurement"]["area_m2"]>0


def test_refinement_rejects_prompts_outside_window(tmp_path):
    path=tmp_path/"single.tif"
    with rasterio.open(path,"w",driver="GTiff",width=64,height=64,count=3,
                       dtype="uint8",crs="EPSG:4326",
                       transform=from_origin(120,32,.00001,.00001)) as dst:
        dst.write(np.zeros((3,64,64),dtype=np.uint8))
    from imagery.raster import RasterError
    with pytest.raises(RasterError):
        refine_raster(path,"test",[120.0002,31.9998],[[121,32]],[],None,64)
