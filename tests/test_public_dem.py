import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from imagery.public_dem import tile_url,_grid,_tile_indices,fetch_dem_subset
from imagery.raster import RasterError

def test_provider_path_and_bounded_grid():
    assert tile_url(31,121,30).endswith("/Copernicus_DSM_COG_10_N31_00_E121_00_DEM.tif")
    assert tile_url(-2,-5,90).endswith("/Copernicus_DSM_COG_30_S02_00_W005_00_DEM.tif")
    crs,affine,w,h=_grid((121.49,31.2,121.51,31.22),30)
    assert crs=="EPSG:32651" and affine.a==30 and 5<=w<=256 and 5<=h<=256
    with pytest.raises(RasterError):_grid((120,30,122,32),30)
    assert len(_tile_indices((121.9,31.9,122.1,32.1)))==4

def test_real_raster_reprojection_and_persistent_provenance(tmp_path,monkeypatch):
    from imagery import public_dem
    src=tmp_path/"source.tif"
    with rasterio.open(src,"w",driver="GTiff",height=120,width=120,count=1,dtype="float32",
                      crs="EPSG:4326",transform=from_origin(121.44,31.26,.001,.001),nodata=-9999) as ds:
        ds.write(np.full((120,120),128,np.float32),1)
    original=rasterio.open
    def open_test(path,*args,**kwargs):
        if str(path).startswith("https://copernicus-dem-"):return original(src)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(public_dem.rasterio,"open",open_test)
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path/"library"))
    result=fetch_dem_subset((121.49,31.2,121.51,31.22),30)
    assert result["resolution_m"]==30 and result["valid_cells"]==result["total_cells"]
    assert result["requested_bbox"]==[121.49,31.2,121.51,31.22]
    assert result["valid_coverage_pct"]==100
    assert "Copernicus DEM GLO-30" in result["asset"]["provenance"]
    from imagery.store import image_file,describe
    uid=result["asset"]["id"]
    assert describe(uid)["provenance"]==result["asset"]["provenance"]
    with original(image_file(uid)) as output:
        assert output.crs.to_epsg()==32651 and np.allclose(output.read(1),128)

def test_unavailable_remote_data_does_not_create_elevation(tmp_path,monkeypatch):
    from imagery import public_dem
    def missing(*args,**kwargs):raise rasterio.errors.RasterioIOError("not available")
    monkeypatch.setattr(public_dem.rasterio,"open",missing)
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path/"library"))
    with pytest.raises(RasterError,match="No public DEM data"):fetch_dem_subset((121.49,31.2,121.51,31.22),30)
    assert not list((tmp_path/"library").glob("*.tif"))

def test_usgs_grid_and_provenance(tmp_path,monkeypatch):
    from imagery import public_dem
    from imagery.store import image_file
    bbox=(-83.001,39.999,-83.,40.)
    crs,affine,w,h=_grid(bbox,1)
    assert affine.a==1 and w<1024 and h<1024
    def fake(bounds,resolution,cancel=None):
        return np.full((h,w),220,np.float32),crs,affine,w*h,[]
    monkeypatch.setattr(public_dem,"_read_usgs",fake)
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path/"library"))
    result=fetch_dem_subset(bbox,1)
    assert "USGS 3DEP Bare Earth DEM" in result["asset"]["provenance"]
    assert "native source resolution varies" in result["asset"]["provenance"]
    with rasterio.open(image_file(result["asset"]["id"])) as ds:
        assert ds.transform.a==1 and np.allclose(ds.read(1),220)

def test_usgs_remote_export_contract_and_error(monkeypatch):
    from contextlib import contextmanager
    import httpx
    from rasterio.io import MemoryFile
    from imagery import public_dem
    bbox=(-83.001,39.999,-83.,40.)
    crs,affine,w,h=_grid(bbox,3)
    with MemoryFile() as memory:
        with memory.open(driver="GTiff",width=w,height=h,count=1,dtype="float32",
                         crs=crs,transform=affine,nodata=-9999) as ds:
            ds.write(np.full((h,w),220,np.float32),1)
        data=memory.read()
    @contextmanager
    def stream(method,url,**kwargs):
        assert method=="GET" and url==public_dem.USGS_EXPORT
        assert kwargs["params"]["pixelType"]=="F32"
        # Raw meter elevations must not activate any color, hillshade or slope renderer.
        assert "renderingRule" not in kwargs["params"]
        assert kwargs["params"]["size"]==f"{w},{h}" and not kwargs["follow_redirects"]
        yield httpx.Response(200,content=data,request=httpx.Request("GET",url))
    monkeypatch.setattr(public_dem.httpx,"stream",stream)
    array,_,_,count,_=public_dem._read_usgs(bbox,3)
    assert count==w*h and np.allclose(array,220)
    @contextmanager
    def wrong_grid(method,url,**kwargs):
        with MemoryFile() as wrong:
            with wrong.open(driver="GTiff",width=w//2,height=h,count=1,dtype="float32",
                            crs=crs,transform=affine,nodata=-9999) as ds:
                ds.write(np.full((h,w//2),220,np.float32),1)
            yield httpx.Response(200,content=wrong.read(),request=httpx.Request("GET",url))
    monkeypatch.setattr(public_dem.httpx,"stream",wrong_grid)
    with pytest.raises(RasterError,match="unexpected raster band count or grid size"):
        public_dem._read_usgs(bbox,3)
    @contextmanager
    def rendered_gray(method,url,**kwargs):
        with MemoryFile() as colorized:
            with colorized.open(driver="GTiff",width=w,height=h,count=1,dtype="uint8",
                                crs=crs,transform=affine) as ds:
                ds.write(np.full((h,w),180,dtype=np.uint8),1)
            yield httpx.Response(200,content=colorized.read(),request=httpx.Request("GET",url))
    monkeypatch.setattr(public_dem.httpx,"stream",rendered_gray)
    with pytest.raises(RasterError,match="display raster"):
        public_dem._read_usgs(bbox,3)
    @contextmanager
    def failure(method,url,**kwargs):
        yield httpx.Response(503,request=httpx.Request("GET",url))
    monkeypatch.setattr(public_dem.httpx,"stream",failure)
    with pytest.raises(RasterError,match="unavailable"):public_dem._read_usgs(bbox,3)
    with pytest.raises(RasterError,match="outside"):public_dem._read_usgs((120,30,120.001,30.001),3)

def test_pre_cancelled_dem_never_reaches_provider(tmp_path,monkeypatch):
    from threading import Event
    from terrain.cancellation import TerrainCancelled
    from imagery import public_dem
    cancel=Event();cancel.set()
    monkeypatch.setattr(public_dem,"_read_usgs",lambda *args,**kwargs:pytest.fail("Provider must not run"))
    with pytest.raises(TerrainCancelled):
        fetch_dem_subset((-83.001,39.999,-83.,40.),3,cancel=cancel)

def test_larger_single_fetch_is_bounded_and_more_than_one_million_cells():
    from imagery.public_dem import MAX_DEM_CELLS,MAX_DEM_SIDE
    bbox=(-83.050,39.98,-82.984,40.036)
    _,_,width,height=_grid(bbox,3)
    assert width*height>1_000_000
    assert width*height<=MAX_DEM_CELLS and max(width,height)<=MAX_DEM_SIDE
    with pytest.raises(RasterError,match="8-million-cell"):
        _grid(bbox,1)


def test_usgs_large_grid_streams_true_georeferenced_chunks_without_gaps(monkeypatch):
    from contextlib import contextmanager
    import httpx
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
    from imagery import public_dem
    bbox=(-83.003,39.998,-82.980,40.001)
    crs,affine,width,height=_grid(bbox,1)
    assert width>public_dem.MAX_USGS_TILE_SIDE and height<public_dem.MAX_USGS_TILE_SIDE
    calls=[]
    @contextmanager
    def stream(method,url,**kwargs):
        assert method=="GET" and url==public_dem.USGS_EXPORT
        size=kwargs["params"]["size"]
        w,h=map(int,size.split(","))
        west,south,east,north=map(float,kwargs["params"]["bbox"].split(","))
        assert w<=public_dem.MAX_USGS_TILE_SIDE and h<=public_dem.MAX_USGS_TILE_SIDE
        # Record the first x coordinate to confirm that remote subrequests
        # have unique exact bounds and no overlap/gap in the output lattice.
        calls.append((west,east,w))
        stamp=from_bounds(west,south,east,north,w,h)
        with MemoryFile() as memory:
            with memory.open(driver="GTiff",width=w,height=h,count=1,dtype="float32",
                             crs=crs,transform=stamp,nodata=-9999) as ds:
                ds.write(np.full((h,w),100+len(calls),dtype=np.float32),1)
            response=httpx.Response(200,content=memory.read(),request=httpx.Request("GET",url))
            yield response
    monkeypatch.setattr(public_dem.httpx,"stream",stream)
    arr,actual_crs,actual_transform,count,missing=public_dem._read_usgs(bbox,1)
    assert actual_crs==crs and actual_transform==affine
    assert count==width*height and not missing
    assert arr.shape==(height,width)
    assert len(calls)>=2
    assert np.allclose(arr[:,:1024],101)
    assert np.allclose(arr[:,1024:],102)
    assert abs(calls[0][1]-calls[1][0])<1e-5


def test_usgs_georeference_mismatch_is_rejected(monkeypatch):
    from contextlib import contextmanager
    import httpx
    from rasterio.io import MemoryFile
    from imagery import public_dem
    bbox=(-83.001,39.999,-83.,40.)
    crs,affine,width,height=_grid(bbox,3)
    @contextmanager
    def wrong_bounds(method,url,**kwargs):
        with MemoryFile() as memory:
            with memory.open(driver="GTiff",width=width,height=height,count=1,
                             dtype="float32",crs=crs,transform=from_origin(
                                 affine.c+1000,affine.f,3,3),nodata=-9999) as ds:
                ds.write(np.full((height,width),220,np.float32),1)
            yield httpx.Response(200,content=memory.read(),request=httpx.Request("GET",url))
    monkeypatch.setattr(public_dem.httpx,"stream",wrong_bounds)
    with pytest.raises(RasterError,match="not aligned"):
        public_dem._read_usgs(bbox,3)
