"""Deterministic readiness, affinity and memory-policy failure contracts."""
import json
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from core import health
from jobs import resources, hard_limits


@pytest.mark.parametrize("database_ok,disk_ok", [(True, True), (True, False),
                                                 (False, True), (False, False)])
def test_readiness_reports_dependency_failure(monkeypatch, tmp_path, database_ok, disk_ok):
    @contextmanager
    def connect():
        if not database_ok:
            raise OSError("database unavailable")
        yield SimpleNamespace(execute=lambda sql: SimpleNamespace(fetchone=lambda: (1,)))
    monkeypatch.setattr(health, "_connect", connect)
    monkeypatch.setattr(health, "database_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(health.shutil, "disk_usage",
                        lambda _: SimpleNamespace(free=64 * 1024**2 if disk_ok else 0))
    result = health.readiness()
    assert result.status_code == (200 if database_ok and disk_ok else 503)
    assert json.loads(result.body)["checks"] == {"database": database_ok, "scratch": disk_ok}


def test_affinity_partitions_slots_and_rejects_overcommit(monkeypatch):
    import psutil
    calls = []
    process = SimpleNamespace(cpu_affinity=lambda *args: calls.append(args[0]) if args else [7, 2, 4, 1])
    monkeypatch.setattr(psutil, "Process", lambda: process)
    monkeypatch.setenv("GEOFATHOM_CPU_CORES_PER_WORKER", "2")
    monkeypatch.setenv("GEOFATHOM_RASTER_AS_MB", "0")
    # configure_child updates three thread-budget variables; restore them after testing.
    for name in ("GEOFATHOM_NATIVE_THREADS", "GEOFATHOM_VISION_CPU_THREADS", "GDAL_NUM_THREADS"):
        monkeypatch.setenv(name, "8")
    resources.configure_child(1)
    assert calls == [[4, 7]]
    assert os.environ["GEOFATHOM_NATIVE_THREADS"] == "2"
    assert os.environ["GDAL_NUM_THREADS"] == "2"
    with pytest.raises(RuntimeError, match="Not enough distinct CPU"):
        resources.configure_child(2)


def test_address_limit_uses_existing_hard_ceiling(monkeypatch):
    calls = []
    fake = SimpleNamespace(RLIMIT_AS=9, RLIM_INFINITY=-1,
        getrlimit=lambda _: (-1, 768*1024**2),
        setrlimit=lambda kind, limits: calls.append((kind, limits)))
    monkeypatch.setitem(sys.modules, "resource", fake)
    monkeypatch.setenv("GEOFATHOM_CPU_CORES_PER_WORKER", "0")
    monkeypatch.setenv("GEOFATHOM_RASTER_AS_MB", "1024")
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE", "cpu")
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE", "cpu")
    resources.configure_child()
    assert calls == [(9, (768*1024**2, 768*1024**2))]
    monkeypatch.setenv("GEOFATHOM_RASTER_AS_MB", "16")
    with pytest.raises(ValueError, match="Address-space limit"):
        resources.configure_child()


@pytest.mark.parametrize("raw", ["-1", "127", "65537", "not-an-int"])
def test_hard_memory_invalid_budget(monkeypatch, raw):
    monkeypatch.setenv("GEOFATHOM_WORKER_MEMORY_MB", raw)
    with pytest.raises(ValueError):
        hard_limits.requested_budget()


def test_hard_memory_dispatch(monkeypatch):
    # Exercise dispatch without joining the pytest process to a kernel object.
    monkeypatch.setenv("GEOFATHOM_WORKER_MEMORY_MB", "512")
    if sys.platform.startswith("linux"):
        monkeypatch.setattr(hard_limits, "_linux_join", lambda limit: limit)
        expected = "cgroup-v2"
    elif os.name == "nt":
        monkeypatch.setattr(hard_limits, "_windows_join", lambda limit, namespace: limit)
        expected = "windows-job-memory"
    else:
        with pytest.raises(RuntimeError, match="unsupported"):
            hard_limits.enforce("test")
        return
    assert hard_limits.enforce("test") == {"mechanism": expected, "limit_bytes": 512*1024**2}
