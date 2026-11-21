from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import rasterio
from rasterio.transform import from_origin
from PIL import Image
import pytest
from imagery.pyramid import DiskTileCache,pyramid_info,render_tile,cached_tile
from imagery.raster import RasterError

def test_pyramid_extents_nodata_and_common_stretch(tmp_path,monkeypatch):
    path=tmp_path/"scene.tif"
    data=np.full((1,257,513),100,np.uint8);data[0,0,0]=0
    with rasterio.open(path,"w",driver="GTiff",width=513,height=257,count=1,
        dtype="uint8",nodata=0,crs="EPSG:4326",transform=from_origin(10,30,.00001,.00001)) as ds:
        ds.write(data)
    info=pyramid_info(path)
    assert info["levels"]==[{"level":0,"factor":1,"columns":3,"rows":2},
      {"level":1,"factor":2,"columns":2,"rows":1},{"level":2,"factor":4,"columns":1,"rows":1}]
    tile=np.array(Image.open(BytesIO(render_tile(path,0,0,0))))
    assert tile.shape==(256,256,4) and tile[0,0,3]==0
    assert tile[1,1].tolist()==[100,100,100,255]
    border=np.array(Image.open(BytesIO(render_tile(path,0,2,1))))
    assert np.count_nonzero(border[:,:,3])==1 and border[0,0,0]==100
    with pytest.raises(RasterError):
        render_tile(path,0,3,0)
    monkeypatch.setenv("GEOFATHOM_TILE_CACHE_PATH",str(tmp_path/"cache.sqlite"))
    original=cached_tile(path,0,0,0)
    assert original==cached_tile(path,0,0,0)
    with rasterio.open(path,"r+") as ds:
        ds.write(np.full_like(data,80))
    assert cached_tile(path,0,0,0)!=original

def test_disk_cache_shared_budget_and_reopen(tmp_path):
    path=tmp_path/"lru.sqlite"
    cache=DiskTileCache(path,128)
    def worker(i):
        return DiskTileCache(path,128).get(str(i%16),lambda:bytes([i%16])*32)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs=list(pool.map(worker,range(64)))
    assert outputs==[bytes([i%16])*32 for i in range(64)]
    assert cache.stats()["payload_bytes"]<=128
    assert cache.stats()["entries"]<=4
    assert DiskTileCache(path,128).stats()==cache.stats()
