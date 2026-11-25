"""Resource policy and real GIS admission regression tests."""
from dataclasses import replace
from threading import Event, Thread
import time

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from rasterio.windows import Window
from shapely.geometry import box, mapping

from core.main import app
from imagery.raster import RasterError
from terrain import compute_resources as cr
from terrain.advanced import _visibility, run_terrain
from terrain.cancellation import TerrainCancelled
from terrain.engine import _native_slope
from terrain.professional import least_cost
from terrain.tiled import analyze_area_tiled


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "_settings_path", lambda: tmp_path/"resources.json")
    hardware=cr.Host(64*cr.GiB, 48*cr.GiB, 16, 100*cr.GiB)
    monkeypatch.setattr(cr, "detect_host", lambda: hardware)
    return hardware


def test_host_scaling_manual_clamps_and_memory_pressure():
    small=cr.resolve_limits(cr.ComputePolicy(), cr.Host(8*cr.GiB,2*cr.GiB,2,cr.GiB))
    big=cr.resolve_limits(cr.ComputePolicy(), cr.Host(64*cr.GiB,48*cr.GiB,16,cr.GiB))
    assert 0 < small.surface_cells < big.surface_cells <= cr.CEILINGS["surface"]
    assert small.global_cells < big.global_cells
    assert big.slope_cells > 32_000_000
    assert big.visibility_cells > 262_144
    assert big.least_cost_cells > 262_144
    policy=cr.ComputePolicy(mode="manual",memory_percent=20,concurrent_tasks=4,
                            tile_size=128,surface_cells=1000,viewshed_distance_m=12345)
    manual=cr.resolve_limits(policy, cr.Host(8*cr.GiB,cr.GiB,2,cr.GiB))
    assert manual.concurrent_tasks==2
    assert manual.memory_bytes*2 <= cr.GiB*3//4
    assert manual.surface_cells==1000 and manual.tile_size==128
    assert manual.viewshed_distance_m==12345
    empty=cr.resolve_limits(policy, cr.Host(8*cr.GiB,32*cr.MiB,2,cr.GiB))
    assert empty.tile_size==0 and empty.surface_cells==0 and empty.slope_cells==0


@pytest.mark.parametrize("patch", [{"memory_percent":99},{"concurrent_tasks":0},
    {"surface_cells":32_000_001},{"tile_size":333},{"ray_samples":1},{"mode":"unknown"},
    {"memory_percent":True},{"unexpected":1}])
def test_strict_resource_validation(patch):
    with pytest.raises(ValidationError):
        cr.ComputePolicy.model_validate(patch)


def test_settings_roundtrip_and_task_snapshot(host):
    policy=cr.ComputePolicy(mode="manual",tile_size=128,concurrent_tasks=1,global_cells=777)
    cr.save_policy(policy)
    assert cr.load_policy()==policy
    with cr.task_resources() as budget:
        assert cr.current_limits()==budget
        assert cr.resource_status()["active_tasks"]==1
        with pytest.raises(cr.ResourceBusy):
            cr.save_policy(cr.ComputePolicy())
        assert budget.global_cells==777
    assert cr.active_limits() is None and cr.resource_status()["active_tasks"]==0


def test_cancellable_queue_and_cleanup(host):
    cr.save_policy(cr.ComputePolicy(mode="manual",concurrent_tasks=1))
    cancel=Event()
    observed=[]
    def queued():
        try:
            with cr.task_resources(cancel):
                observed.append("unexpected")
        except TerrainCancelled:
            observed.append("cancelled")
    with cr.task_resources():
        t=Thread(target=queued)
        t.start()
        try:
            deadline=time.monotonic()+5
            while cr.resource_status()["queued_tasks"]!=1 and time.monotonic()<deadline:
                time.sleep(.01)
            assert cr.resource_status()["queued_tasks"]==1
        finally:
            cancel.set()
            t.join(timeout=5)
        assert not t.is_alive() and observed==["cancelled"]
    assert cr.resource_status()["active_tasks"]==cr.resource_status()["queued_tasks"]==0


def test_low_memory_refuses_before_allocation(host, monkeypatch):
    monkeypatch.setattr(cr,"detect_host",lambda: cr.Host(8*cr.GiB,32*cr.MiB,4,cr.GiB))
    with pytest.raises(cr.ResourceBusy,match="Insufficient"):
        with cr.task_resources():
            pytest.fail("Task must not enter its allocation phase")
    assert cr.resource_status()["active_tasks"]==0


def fixture(path, rows=30, cols=30):
    yy,xx=np.mgrid[:rows,:cols]
    z=(100+xx*.7+yy*.3).astype(np.float32)
    z[4:7,6:9]=-9999
    affine=from_origin(500000,4500000,10,10)
    with rasterio.open(path,"w",driver="GTiff",height=rows,width=cols,count=1,
                       dtype="float32",crs="EPSG:32617",transform=affine,nodata=-9999) as dst:
        dst.write(z,1)
    with rasterio.open(path) as src:
        polygon=mapping(box(*src.bounds).buffer(1))
        geo=transform_geom(src.crs,"EPSG:4326",polygon)
    return geo


def test_api_budget_enforces_real_grid_and_preserves_result(host,tmp_path,monkeypatch):
    path=tmp_path/"plane.tif"
    geo=fixture(path)
    import terrain.routes as routes
    monkeypatch.setattr(routes,"raster",lambda identifier:path)
    client=TestClient(app)
    initial=client.get("/terrain/resources")
    assert initial.status_code==200 and initial.json()["policy"]["mode"]=="automatic"
    assert client.put("/terrain/resources",json={"mode":"manual","memory_percent":100}).status_code==422
    policy=cr.ComputePolicy(mode="manual",surface_cells=100,concurrent_tasks=1)
    assert client.put("/terrain/resources",json=policy.model_dump()).status_code==200
    body={"image_id":"fixture","geometry":geo,"operation":"elevation"}
    denied=client.post("/terrain/advanced",json=body)
    assert denied.status_code==422 and "100 pixels" in denied.json()["detail"]
    allowed=policy.model_copy(update={"surface_cells":1000})
    assert client.put("/terrain/resources",json=allowed.model_dump()).status_code==200
    result=client.post("/terrain/advanced",json=body)
    assert result.status_code==200,result.text[:500]
    actual=result.json()
    expected=run_terrain(path,geo,"elevation")
    assert actual["valid_cells"]==expected["valid_cells"]
    assert actual["metrics"]==expected["metrics"]
    assert actual["compute_resources"]["surface_cells"]==1000
    assert client.get("/terrain/resources").json()["active_tasks"]==0


def test_configured_tiles_preserve_halo_science(host,tmp_path):
    path=tmp_path/"seams.tif"
    geo=fixture(path,260,280)
    cr.save_policy(cr.ComputePolicy(mode="manual",tile_size=128,concurrent_tasks=1))
    with rasterio.open(path) as src:
        projected=transform_geom("EPSG:4326",src.crs,geo)
        raw=src.read(1,masked=True)
        z=raw.filled(np.nan)
        valid=np.isfinite(z)
        expected=_native_slope(z,valid,10,10)
        with cr.task_resources():
            result=analyze_area_tiled(src,projected,Window(0,0,src.width,src.height))
        assert result["gradient_pixels"]==expected["gradient_pixels"]
        assert result["valid_pixels"]==int(valid.sum())
        assert result["mean_slope_deg"]==pytest.approx(expected["mean_slope_deg"],abs=.002)


def test_global_algorithms_keep_exact_semantics_and_enforce_selected_limits(host):
    z=np.zeros((5,5))
    valid=np.ones_like(z,dtype=bool)
    transform=from_origin(0,50,10,10)
    reference=_visibility(z,valid,(0,0),transform,1.7,0)
    policy=cr.ComputePolicy(mode="manual",least_cost_cells=16,viewshed_distance_m=100)
    cr.save_policy(policy)
    with cr.task_resources():
        result=_visibility(z,valid,(0,0),transform,1.7,0)
        assert all(np.array_equal(a,b) for a,b in zip(reference,result))
        with pytest.raises(RasterError,match="16 cells"):
            least_cost(z,valid,(0,0),(4,4),10,10,45)
        with pytest.raises(RasterError,match="0.1 km"):
            _visibility(z,valid,(0,0),from_origin(0,500,100,100),1.7,0)
