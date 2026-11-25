"""Real spawned-worker IPC acceptance for isolated GDAL/ONNX task infrastructure."""
from threading import Event
import os

import pytest

from jobs import leases,queue
from jobs.isolation import run_isolated
from storage.database import _connect,create_project,database_path


def test_spawned_raster_runner_returns_real_json_and_preserves_owner(
        monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"isolate.sqlite"))
    monkeypatch.setenv("GEOFATHOM_EXTERNAL_WORKER","1")
    project=create_project("isolated process")["id"]
    uid=queue.queue_job(project,"export_geojson",{})["id"]
    owner="isolation-test-"+uid
    with _connect() as c:
        queue._schema(c)
        assert leases.claim(c,uid,owner) is not None
    output=run_isolated(str(database_path().resolve()),uid,owner,
                        "export_geojson",project,{},Event())
    assert output["type"]=="FeatureCollection"
    assert output["features"]==[]
    with _connect() as c:
        assert leases.is_owner(c,uid,owner)


def test_wall_time_and_memory_budget_config_rejects_invalid_env(monkeypatch):
    from jobs.isolation import _limit
    monkeypatch.setenv("GEOFATHOM_RASTER_RSS_MB","not-number")
    with pytest.raises(ValueError,match="integer"):
        _limit("GEOFATHOM_RASTER_RSS_MB",2048,256,16384)
    monkeypatch.setenv("GEOFATHOM_RASTER_RSS_MB","1")
    with pytest.raises(ValueError,match="between"):
        _limit("GEOFATHOM_RASTER_RSS_MB",2048,256,16384)
