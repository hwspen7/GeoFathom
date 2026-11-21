"""Allowlisted remote STAC/COG raster reads and cloud-mask integration."""
from contextlib import contextmanager
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from imagery import remote
from imagery.raster import RasterError
from vision.quality import (confusion_matrix,metrics_from_matrix,
                            sentinel2_clear_mask)

HOST="e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com"


def test_remote_url_never_accepts_arbitrary_host_or_query(monkeypatch):
    good="https://"+HOST+"/sentinel/test/B08.tif"
    assert remote.vetted_asset_href(good)==good
    for bad in (
        "http://"+HOST+"/a.tif",
        "https://127.0.0.1/a.tif",
        "https://"+HOST+"/../private.tif",
        "https://"+HOST+"/a.tif?signature=secret",
        "https://"+HOST+"@127.0.0.1/a.tif",
        "https://"+HOST+":8080/a.tif",
        "file:///etc/passwd",
        "https://evil.invalid/a.tif",
    ):
        with pytest.raises(RasterError):
            remote.vetted_asset_href(bad)
    monkeypatch.setenv("GEOFATHOM_COG_ALLOWED_HOSTS","example.org")
    with pytest.raises(RasterError):
        remote.vetted_asset_href(good)


def test_stac_fetch_rejects_wrong_identity_and_oversized_metadata(monkeypatch):
    class Response:
        def __init__(self,data):
            self.data=data
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def raise_for_status(self):pass
        def iter_bytes(self):
            yield self.data
    class Client:
        def __init__(self,data):
            self.data=data
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def stream(self,method,url,headers):
            assert method=="GET"
            assert url.startswith("https://earth-search.aws.element84.com/v1/")
            return Response(self.data)
    monkeypatch.setattr(remote.httpx,"Client",
                        lambda **kwargs:Client(b'{"id":"wrong"}'))
    with pytest.raises(RasterError,match="does not match"):
        remote.fetch_stac_item("sentinel-2-c1-l2a","S2_2024_demo")
    monkeypatch.setattr(remote.httpx,"Client",
                        lambda **kwargs:Client(b"x"*1_000_001))
    with pytest.raises(RasterError,match="exceeds"):
        remote.fetch_stac_item("sentinel-2-c1-l2a","S2_2024_demo")
    with pytest.raises(RasterError,match="invalid"):
        remote.fetch_stac_item("sentinel-2-c1-l2a","../metadata")


def test_stac_ndvi_streams_separate_bands_and_excludes_scl_clouds(
        monkeypatch,tmp_path):
    transform=from_origin(120,32,.00001,.00001)
    specs={"nir":200,"red":50,"scl":4}
    images={}
    for name,value in specs.items():
        path=tmp_path/(name+".tif")
        pixels=np.full((128,128),value,dtype=np.uint16)
        if name=="scl":
            pixels[16:32,16:32]=9
        with rasterio.open(path,"w",driver="GTiff",count=1,
                           width=128,height=128,dtype="uint16",
                           crs="EPSG:4326",transform=transform,nodata=0) as dst:
            dst.write(pixels,1)
        images[name]=path
    hrefs={name:"https://"+HOST+"/demo/"+name+".tif"
           for name in images}
    item={"id":"S2_2024_demo","collection":"sentinel-2-c1-l2a",
          "properties":{"datetime":"2024-10-01T00:00:00Z"},
          "assets":{name:{"href":href} for name,href in hrefs.items()}}
    monkeypatch.setattr(remote,"fetch_stac_item",
                        lambda collection,item_id:item)
    actual_open=remote.rasterio.open
    def mapped_open(target,*args,**kwargs):
        for name,url in hrefs.items():
            if target=="/vsicurl/"+url:
                return actual_open(images[name],*args,**kwargs)
        return actual_open(target,*args,**kwargs)
    monkeypatch.setattr(remote.rasterio,"open",mapped_open)
    result=remote.run_stac_ndvi("sentinel-2-c1-l2a","S2_2024_demo",
                                threshold=.3,max_side=128,
                                tile_size=64,max_pixels=20000,memory_mb=16)
    assert result["classified_pixels"]==128*128-16*16
    assert result["cloud_excluded_pixels"]==16*16
    assert len(result["features"])==1
    assert result["features"][0]["properties"]["pixel_count"]==128*128-16*16
    assert result["resolution_reduced"] is False
    assert result["engine"].startswith("gdal-vsicurl+")
    assert result["acquired_at"]=="2024-10-01T00:00:00Z"


def test_quality_confusion_and_sentinel_scl_masks():
    scl=np.array([[4,5,6,7],[0,1,3,9],[10,11,2,8]])
    expected=np.array([[1,1,1,1],[0,0,0,0],[0,0,0,0]],bool)
    np.testing.assert_array_equal(sentinel2_clear_mask(scl),expected)
    truth=np.array([[0,0],[1,1]],dtype=np.uint8)
    predicted=np.array([[0,1],[1,0]],dtype=np.uint8)
    matrix=confusion_matrix(truth,predicted,2)
    assert matrix.tolist()==[[1,1],[1,1]]
    result=metrics_from_matrix(matrix,["background","target"])
    assert result["overall_accuracy"]==.5
    assert result["mean_iou_present_classes"]==pytest.approx(1/3)
    assert all(x["f1"]==.5 for x in result["classes"])
