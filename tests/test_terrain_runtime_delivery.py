"""Real storage, isolated process and hardware-selection contracts."""
from dataclasses import replace
from threading import Event
import hashlib
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from shapely.geometry import box,mapping

from core.main import app
from imagery.raster import RasterError
from terrain import compute_resources as cr
from terrain import cuda_terrain,isolated_worker
from terrain.engine import analyze_area
from terrain.professional import raster_product
from terrain.products import product_path,temporary_product,publish


@pytest.fixture
def host(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path))
    monkeypatch.setattr(cr,"_settings_path",lambda:tmp_path/"settings.json")
    hardware=cr.Host(32*cr.GiB,20*cr.GiB,8,100*cr.GiB)
    monkeypatch.setattr(cr,"detect_host",lambda:hardware)
    return hardware


def test_gpu_budget_caps_and_explicit_cpu_fallback(host,monkeypatch):
    hardware=replace(host,gpu_total_bytes=16*cr.GiB,gpu_free_bytes=400*cr.MiB)
    automatic=cr.resolve_limits(cr.ComputePolicy(),hardware)
    assert automatic.gpu_memory_bytes==200*cr.MiB
    assert cr.resolve_limits(cr.ComputePolicy(backend="cpu"),hardware).gpu_memory_bytes==0
    monkeypatch.setattr(cuda_terrain,"_native",lambda:None)
    assert cuda_terrain.device_memory()==(0,0)
    z=np.zeros((10,10),np.float32)
    assert cuda_terrain.gradients(z,np.ones_like(z,bool),1.,1.,"horn",cr.MiB) is None


def test_large_product_exact_download_range_and_removal(host,tmp_path):
    rows,cols=1001,1001
    z=np.broadcast_to(np.arange(cols,dtype=np.float64),(rows,cols)).copy()
    z[12:19,4:8]=np.nan
    affine=from_origin(500000,4500000,10,10)
    with cr.task_resources():
        result=raster_product(z,"elevation",affine,"EPSG:32617")
    assert result["geotiff"]==""
    identifier=result["product_id"]
    path=product_path(identifier)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==identifier
    with rasterio.open(path) as src:
        np.testing.assert_array_equal(src.read(1),z.astype(np.float32))
        assert src.transform==affine
        assert src.tags()["TERRAIN_OPERATION"]=="elevation"
    client=TestClient(app)
    listed=client.get("/terrain/products")
    assert listed.status_code==200
    assert listed.json()["products"][0]["id"]==identifier
    download=client.get("/terrain/products/"+identifier)
    assert download.status_code==200 and download.content==path.read_bytes()
    ranged=client.get("/terrain/products/"+identifier,headers={"Range":"bytes=0-63"})
    assert ranged.status_code==206 and ranged.content==path.read_bytes()[:64]
    assert client.delete("/terrain/products/"+identifier).status_code==200
    assert client.get("/terrain/products/"+identifier).status_code==404
    with pytest.raises(RasterError):product_path("../secret")


def test_product_deduplicates_and_checks_quota(host,monkeypatch):
    from terrain import products
    with temporary_product(100) as a:
        a.write_bytes(b"first")
        first=publish(a)
    with temporary_product(100) as b:
        b.write_bytes(b"first")
        assert publish(b)==first
    monkeypatch.setattr(products,"_MAX_FILES",1)
    with temporary_product(100) as c:
        c.write_bytes(b"second")
        with pytest.raises(RasterError,match="storage is full"):publish(c)
    assert not list(products.root().glob(".writing-*"))


def test_isolated_worker_real_dem_and_unavailable_hard_limit(host,tmp_path,monkeypatch):
    path=tmp_path/"worker.tif";affine=from_origin(500000,4500000,10,10)
    z=np.broadcast_to(np.arange(32,dtype=np.float32),(32,32)).copy()
    with rasterio.open(path,"w",driver="GTiff",height=32,width=32,count=1,
                       dtype="float32",crs="EPSG:32617",transform=affine) as dst:dst.write(z,1)
    with rasterio.open(path) as src:
        polygon=transform_geom(src.crs,"EPSG:4326",mapping(box(*src.bounds)))
    limits=cr.resolve_limits(cr.ComputePolicy(backend="cpu"),host)
    args=(path,polygon,"meter","horn")
    expected=analyze_area(*args)
    actual=isolated_worker.isolated_call(analyze_area,args,limits,Event(),hard=False)
    assert actual["gradient_pixels"]==expected["gradient_pixels"]
    assert actual["mean_slope_deg"]==pytest.approx(expected["mean_slope_deg"])
    monkeypatch.setattr(isolated_worker,"hard_memory_available",lambda:False)
    with pytest.raises(cr.ResourceBusy,match="Hard memory mode"):
        isolated_worker.isolated_call(analyze_area,args,limits,Event(),hard=True)
    with pytest.raises(cr.ResourceBusy,match="Hard memory mode"):
        cr.save_policy(cr.ComputePolicy(hard_memory=True))


def test_mesh_large_grid_budget_and_real_tile(host,tmp_path):
    from terrain.mesh_tiles import stream_mesh_tile
    path=tmp_path/"mesh.tif"
    affine=from_origin(500000,4500000,10,10)
    # A 4097-wide real raster exceeds the former fixed axis cap but one tile
    # needs only a small source window.
    z=np.broadcast_to(np.arange(4097,dtype=np.float32),(32,4097)).copy()
    with rasterio.open(path,"w",driver="GTiff",height=32,width=4097,count=1,
                       dtype="float32",crs="EPSG:32617",transform=affine) as dst:dst.write(z,1)
    with rasterio.open(path) as src:
        polygon=transform_geom(src.crs,"EPSG:4326",mapping(box(*src.bounds)))
    with cr.task_resources():
        tile=stream_mesh_tile(path,polygon,1,0,0)
    assert tile["grid_cols"]==4097
    assert tile["maximum_vertical_error_m"]==pytest.approx(0) if "maximum_vertical_error_m" in tile else tile["cols"]==33
