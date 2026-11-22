"""Regression tests for fail-closed native identity and subprocess IPC."""
import json
from types import SimpleNamespace

import pytest

from geometry import cuda, topology
from jobs import isolation


@pytest.fixture
def clean_native(monkeypatch):
    topology._native.cache_clear()
    monkeypatch.delenv("GEOFATHOM_NATIVE_LIBRARY", raising=False)
    monkeypatch.delenv("GEOFATHOM_REQUIRE_NATIVE", raising=False)
    yield
    topology._native.cache_clear()


def test_missing_pinned_library_does_not_fallback(clean_native, monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFATHOM_NATIVE_LIBRARY", str(tmp_path / "not-built.dll"))
    calls = []
    monkeypatch.setattr(topology.ctypes, "CDLL", lambda path: calls.append(path))
    with pytest.raises(RuntimeError, match="Required native library"):
        topology._native()
    assert calls == []


def test_broken_pinned_library_does_not_fallback(clean_native, monkeypatch, tmp_path):
    path = tmp_path / "broken.dll"
    path.touch()
    monkeypatch.setenv("GEOFATHOM_NATIVE_LIBRARY", str(path))
    calls = []
    def load(target):
        calls.append(target)
        raise OSError("missing dependency")
    monkeypatch.setattr(topology.ctypes, "CDLL", load)
    with pytest.raises(RuntimeError, match="missing dependency"):
        topology._native()
    assert calls == [str(path.resolve())]


@pytest.fixture
def fake_cuda(monkeypatch):
    # Preserve the real process-wide owner (other tests may have used CUDA).
    for name in ("_owner", "_library", "_policy"):
        monkeypatch.setattr(cuda, name, None)
    monkeypatch.setenv("GEOFATHOM_CUDA_SPECTRAL_MAX_PIXELS", "1024")
    monkeypatch.setenv("GEOFATHOM_CUDA_SPECTRAL_BUDGET_MB", "256")
    monkeypatch.setenv("GEOFATHOM_CUDA_DEVICE_ID", "0")
    calls = []
    def create(capacity, device):
        calls.append(("create", capacity, device))
        return 123
    def destroy(owner):
        calls.append(("destroy", owner))
    def trim(owner):
        calls.append(("trim", owner))
        return 0
    def stats(owner, out):
        out[:] = [128, 1024, 1920]
        return 0
    lib = SimpleNamespace(gf_cuda_runtime_create=create,
                          gf_cuda_runtime_destroy=destroy,
                          gf_cuda_runtime_trim=trim,
                          gf_cuda_runtime_stats=stats)
    yield lib, calls
    cuda._close()


def test_cuda_owner_reuse_trim_stats_and_configuration_fencing(fake_cuda, monkeypatch):
    lib, calls = fake_cuda
    assert cuda.stats()["allocated_bytes"] == 0
    assert cuda.handle(lib, 100) == cuda.handle(lib, 120) == 123
    cuda.trim()
    assert cuda.stats() == {"capacity_pixels": 128, "limit_pixels": 1024, "allocated_bytes": 1920}
    monkeypatch.setenv("GEOFATHOM_CUDA_DEVICE_ID", "1")
    with pytest.raises(RuntimeError, match="configuration changed"):
        cuda.handle(lib, 120)
    cuda._close()
    assert calls == [("create", 1024, 0), ("trim", 123), ("destroy", 123)]
    assert cuda.stats()["allocated_bytes"] == 0


@pytest.mark.parametrize("count", [0, -1, 1025])
def test_cuda_rejects_invalid_count(fake_cuda, count):
    lib, calls = fake_cuda
    with pytest.raises(ValueError, match="capacity"):
        cuda.handle(lib, count)
    assert not calls


def test_cuda_allocation_failure_can_retry(fake_cuda):
    lib, calls = fake_cuda
    create = lib.gf_cuda_runtime_create
    def fail(*args):
        return None
    lib.gf_cuda_runtime_create = fail
    with pytest.raises(RuntimeError, match="allocation failed"):
        cuda.handle(lib, 100)
    lib.gf_cuda_runtime_create = create
    assert cuda.handle(lib, 100) == 123


@pytest.mark.parametrize("payload", [b"broken", b"[]", b"null", b'{"status":"ok"}',
                                    b'{"status":"other"}', b'{"status":"error","error":1}'])
def test_invalid_ipc_envelope(payload):
    receive = SimpleNamespace(recv_bytes=lambda maxlength: payload)
    with pytest.raises(RuntimeError, match="IPC"):
        isolation._read_result(receive)


def test_ipc_error_and_valid_result():
    def read(record):
        return isolation._read_result(SimpleNamespace(
            recv_bytes=lambda maxlength: json.dumps(record).encode()))
    with pytest.raises(RuntimeError, match="child failed"):
        read({"status": "error", "error": "child failed"})
    assert read({"status": "ok", "result": {"value": 1}}) == {"value": 1}


def test_ipc_eof_is_reported():
    def eof(maxlength):
        raise EOFError()
    with pytest.raises(RuntimeError, match="IPC"):
        isolation._read_result(SimpleNamespace(recv_bytes=eof))
