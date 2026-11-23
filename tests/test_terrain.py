"""Known planar DEM: slope, area statistics and profile output."""
import os

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_origin

from core.main import app
from terrain.engine import _native_slope,analyze_area,elevation_profile

client=TestClient(app)


@pytest.fixture
def dem(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path))
    path=tmp_path/"test-elev.tif"
    z=np.array([[100+float(x) for x in range(100)] for y in range(100)],dtype="float32")
    transform=from_origin(500000,4500000,10,10)
    with rasterio.open(path,"w",driver="GTiff",width=100,height=100,
        count=1,dtype="float32",crs="EPSG:32617",transform=transform,nodata=-9999) as dst:
        dst.write(z,1)
    def xy(x,y):
        conv=Transformer.from_crs("EPSG:32617","EPSG:4326",always_xy=True)
        return list(conv.transform(x,y))
    poly={"type":"Polygon","coordinates":[[
        xy(500100,4499900),xy(500700,4499900),
        xy(500700,4499300),xy(500100,4499300),xy(500100,4499900),
    ]]}
    line={"type":"LineString","coordinates":[xy(500150,4499850),xy(500650,4499850)]}
    return path,poly,line


def test_slope_of_known_plane(dem):
    path,poly,line=dem
    result=analyze_area(path,poly)
    assert 5.70<result["mean_slope_deg"]<5.72
    assert result["maximum_slope_deg"]==pytest.approx(result["mean_slope_deg"],abs=.001)
    assert 100<result["elevation_min_m"]<199
    assert result["valid_pixels"]>1000
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE")=="1":
        assert result["engine"]=="cpp-horn"


def test_dem_profile_and_geo_coordinate_policy(dem):
    path,poly,line=dem
    result=elevation_profile(path,line,20)
    assert len(result["samples"])==20
    assert result["length_m"]>400
    assert result["samples"][-1]["elevation_m"]>result["samples"][0]["elevation_m"]
    from imagery.store import store_upload
    from shutil import copyfile
    # Managed uploads are canonical UUID images; no arbitrary raster file path from clients.
    renamed=path.parent/"upload.tif"
    copyfile(path,renamed)
    meta=store_upload(renamed,"dem.tif")
    r=client.post("/terrain/analyze",json={"image_id":meta["id"],"geometry":poly})
    assert r.status_code==200,r.text

    # API metadata must never claim feet while returning meter elevations.
    profile=client.post("/terrain/profile",json={
        "image_id":meta["id"],"geometry":line,"samples":20,"vertical_unit":"meter"})
    assert profile.status_code==200,profile.text
    assert profile.json()["vertical_unit"]=="meter"
    for endpoint,region in (("/terrain/profile",line),("/terrain/analyze",poly)):
        rejected=client.post(endpoint,json={
            "image_id":meta["id"],"geometry":region,"vertical_unit":"foot"})
        assert rejected.status_code==422,rejected.text
        assert "meters only" in rejected.json()["detail"]
