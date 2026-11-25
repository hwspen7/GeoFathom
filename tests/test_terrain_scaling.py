"""Independent path/flow references and large, real raster scaling contracts."""
import math
import sqlite3
import time
from threading import Event

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
from shapely.geometry import box,mapping

from imagery.raster import RasterError
from terrain import compute_resources as cr
from terrain.cancellation import checkpoint,TerrainCancelled
from terrain.graph_kernels import exact_route
from terrain.professional import least_cost,D8,d8_flow
from terrain.multiflow import mfd_accumulation
from terrain.scientific_kernels import dinfinity_accumulation
from terrain import tiled


@pytest.fixture
def host(monkeypatch,tmp_path):
    monkeypatch.setattr(cr,"_settings_path",lambda:tmp_path/"policy.json")
    hardware=cr.Host(64*cr.GiB,48*cr.GiB,16,100*cr.GiB)
    monkeypatch.setattr(cr,"detect_host",lambda:hardware)
    return hardware


@pytest.mark.parametrize("model",["distance","surface","gentle"])
@pytest.mark.parametrize("disk",[False,True])
def test_indexed_route_matches_reference_on_anisotropic_masked_grid(tmp_path,model,disk):
    rng=np.random.default_rng(25)
    z=rng.normal(0,.5,(25,37))
    valid=np.ones_like(z,dtype=bool)
    valid[2:22,18]=False
    valid[12,18]=True
    expected,cost=least_cost(z,valid,(0,0),(24,36),9.,13.,45.,route_model=model)
    scratch=tmp_path if disk else None
    actual,value=exact_route(z,valid,(0,0),(24,36),9.,13.,45.,model,D8,scratch=scratch)
    assert actual==expected
    assert value==pytest.approx(cost,rel=1e-12)
    assert not list(tmp_path.glob("route-*"))


def test_disk_route_no_path_cleans_up_and_cancel(tmp_path):
    z=np.zeros((8,8))
    valid=np.ones_like(z,dtype=bool)
    valid[:,3]=False
    with pytest.raises(RasterError,match="No valid terrain route"):
        exact_route(z,valid,(0,0),(7,7),10.,10.,45.,"distance",D8,scratch=tmp_path)
    assert not list(tmp_path.glob("route-*"))
    event=Event();event.set()
    with pytest.raises(TerrainCancelled):
        exact_route(z,valid,(0,0),(7,7),10.,10.,45.,"distance",D8,event,tmp_path)
    assert not list(tmp_path.glob("route-*"))


def test_compiled_mfd_matches_scalar_reference(host):
    rng=np.random.default_rng(123)
    z=rng.random((35,41))
    valid=rng.random(z.shape)>.1
    expected=mfd_accumulation(z,valid,7.,12.,1.4)
    with cr.task_resources():
        actual=mfd_accumulation(z,valid,7.,12.,1.4)
    np.testing.assert_allclose(actual,expected,atol=1e-12,rtol=1e-12,equal_nan=True)


def test_global_flow_above_legacy_million_cell_ceiling(host):
    rows,cols=1024,1025
    z=np.tile(np.arange(cols,dtype=np.float64),(rows,1))
    valid=np.ones_like(z,dtype=bool)
    with cr.task_resources():
        _,_,d8=d8_flow(z,valid,10.,10.)
        mfd=mfd_accumulation(z,valid,10.,10.)
        dinf,_=dinfinity_accumulation(z,valid,10.,10.)
    assert np.all(d8[:,0]==cols)
    for values in (mfd,dinf):
        assert np.isfinite(values).all()
        assert values[:,0].sum()==pytest.approx(rows*cols,rel=1e-10)
    print(f"Global flow acceptance: {rows*cols:,} cells; outlet flux conserved.")


def write_plane(path,rows,cols):
    affine=from_origin(500000,4500000,10,10)
    with rasterio.open(path,"w",driver="GTiff",height=rows,width=cols,count=1,
        dtype="float32",crs="EPSG:32617",transform=affine,nodata=-9999,
        tiled=True,blockxsize=256,blockysize=256,compress="deflate") as dst:
        for r in range(0,rows,256):
            h=min(256,rows-r)
            data=np.broadcast_to(np.arange(cols,dtype=np.float32), (h,cols)).copy()
            dst.write(data,1,window=Window(0,r,cols,h))
    return affine


def test_resume_real_tiles_and_invalidate_changed_inputs(host,tmp_path,monkeypatch):
    path=tmp_path/"resume.tif";write_plane(path,330,350)
    root=tmp_path/"checkpoints"
    cr.save_policy(cr.ComputePolicy(mode="manual",tile_size=128,concurrent_tasks=1))
    cancel=Event();original=tiled._tile
    calls=[]
    def interrupt(*args,**kwargs):
        value=original(*args,**kwargs)
        calls.append(1)
        if len(calls)==3:cancel.set()
        return value
    with rasterio.open(path) as src:
        polygon=mapping(box(*src.bounds));window=Window(0,0,src.width,src.height)
        with cr.task_resources():
            monkeypatch.setattr(tiled,"_tile",interrupt)
            with pytest.raises(TerrainCancelled):
                tiled.analyze_area_tiled(src,polygon,window,cancel,checkpoint_root=root)
        with sqlite3.connect(root/"slope-checkpoints.sqlite") as db:
            assert db.execute("SELECT count(*) FROM slope_tiles").fetchone()[0]==3
        monkeypatch.setattr(tiled,"_tile",original)
        with cr.task_resources():
            result=tiled.analyze_area_tiled(src,polygon,window,checkpoint_root=root)
            reference=tiled.analyze_area_tiled(src,polygon,window)
        assert result["tiles_resumed"]==3
        assert result["tiles_processed"]==9
        assert {k:v for k,v in result.items() if k!="tiles_resumed"}=={k:v for k,v in reference.items() if k!="tiles_resumed"}
        with sqlite3.connect(root/"slope-checkpoints.sqlite") as db:
            assert db.execute("SELECT count(*) FROM slope_tiles").fetchone()[0]==0
        # Cancel another run, then change geometry: previous tile sums cannot be reused.
        cancel.clear();calls.clear()
        with cr.task_resources():
            monkeypatch.setattr(tiled,"_tile",interrupt)
            with pytest.raises(TerrainCancelled):
                tiled.analyze_area_tiled(src,polygon,window,cancel,checkpoint_root=root)
        monkeypatch.setattr(tiled,"_tile",original)
        changed=mapping(box(src.bounds.left,src.bounds.bottom,src.bounds.right-10,src.bounds.top))
        with cr.task_resources():
            result=tiled.analyze_area_tiled(src,changed,window,checkpoint_root=root)
        assert result["tiles_resumed"]==0
        assert result["valid_pixels"]==330*349


def test_real_large_streamed_dem(host,tmp_path):
    rows,cols=4097,4097
    path=tmp_path/"large.tif";write_plane(path,rows,cols)
    cr.save_policy(cr.ComputePolicy(mode="manual",tile_size=512,concurrent_tasks=1))
    start=time.monotonic()
    with rasterio.open(path) as src,cr.task_resources():
        result=tiled.analyze_area_tiled(src,mapping(box(*src.bounds)),
            Window(0,0,cols,rows),checkpoint_root=tmp_path/"checkpoints")
    assert result["valid_pixels"]==rows*cols
    assert result["gradient_pixels"]==(rows-2)*(cols-2)
    assert result["mean_slope_deg"]==pytest.approx(math.degrees(math.atan(.1)),abs=.001)
    assert result["elevation_mean_m"]==pytest.approx((cols-1)/2)
    assert result["tiles_processed"]==81
    print(f"Streamed {rows*cols:,} DEM cells, 512-cell tiles, {time.monotonic()-start:.2f} seconds.")


def test_runtime_memory_pressure_releases_reservation(host,monkeypatch):
    clock=[100.]
    monkeypatch.setattr(cr.time,"monotonic",lambda:clock[0])
    try:
        with cr.task_resources() as limits:
            assert cr.resource_status()["reserved_bytes"]==limits.memory_bytes
            monkeypatch.setattr(cr,"detect_host",lambda:cr.Host(8*cr.GiB,64*cr.MiB,4,cr.GiB))
            clock[0]+=1
            checkpoint()
    except cr.ResourceBusy as error:
        assert "critically low" in str(error)
    else:
        pytest.fail("Memory-pressure guard failed")
    assert cr.resource_status()["reserved_bytes"]==0
    assert cr.resource_status()["active_tasks"]==0
