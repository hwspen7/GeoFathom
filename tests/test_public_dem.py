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
