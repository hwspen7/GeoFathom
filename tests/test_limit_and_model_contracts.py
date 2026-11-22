"""Fail-closed cgroup configuration and optional SAM dependency contracts."""
from pathlib import Path
from types import SimpleNamespace,ModuleType
import sys
import pytest
from jobs import hard_limits
from vision import sam


@pytest.fixture
def cgroup(monkeypatch,tmp_path):
    root=tmp_path/"cgroup";root.mkdir()
    group=root/"delegated";group.mkdir()
    (group/"memory.max").write_text(str(256*1024**2))
    (group/"cgroup.procs").write_text("")
    monkeypatch.setattr(hard_limits,"Path",lambda p:root if str(p)=="/sys/fs/cgroup" else Path(p))
    monkeypatch.setenv("GEOFATHOM_WORKER_CGROUP",str(group))
    return root,group


def test_cgroup_attachment_checks_real_files_in_isolated_fixture(cgroup):
    _,group=cgroup
    assert hard_limits._linux_join(512*1024**2)==256*1024**2
    import os
    assert (group/"cgroup.procs").read_text()==str(os.getpid())


@pytest.mark.parametrize("limit",["max","0","536870913","invalid"])
def test_cgroup_upper_limit_fail_closed(cgroup,limit):
    _,group=cgroup
    (group/"memory.max").write_text(limit)
    with pytest.raises((RuntimeError,ValueError)):
        hard_limits._linux_join(512*1024**2)
    assert (group/"cgroup.procs").read_text()==""


def test_cgroup_rejects_undelegated_and_outside_root(cgroup,monkeypatch,tmp_path):
    monkeypatch.delenv("GEOFATHOM_WORKER_CGROUP")
    with pytest.raises(RuntimeError,match="provisioned"):
        hard_limits._linux_join(512*1024**2)
    monkeypatch.setenv("GEOFATHOM_WORKER_CGROUP",str(tmp_path))
    with pytest.raises(RuntimeError,match="below"):
        hard_limits._linux_join(512*1024**2)


@pytest.fixture
def predictor_cache():
    sam._predictor.cache_clear()
    yield
    sam._predictor.cache_clear()


def test_sam_disabled_missing_dependencies_and_cpu_only(predictor_cache,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED","0")
    with pytest.raises(sam.VisionUnavailable,match="disabled"):
        sam._predictor()
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED","1")
    monkeypatch.setitem(sys.modules,"torch",None)
    with pytest.raises(sam.VisionUnavailable,match="Install PyTorch"):
        sam._predictor()
    monkeypatch.setitem(sys.modules,"torch",SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False)))
    module=ModuleType("sam2.sam2_image_predictor")
    module.SAM2ImagePredictor=SimpleNamespace(from_pretrained=lambda name:None)
    monkeypatch.setitem(sys.modules,"sam2.sam2_image_predictor",module)
    with pytest.raises(sam.VisionUnavailable,match="requires CUDA"):
        sam._predictor()


def test_sam_predictor_loads_configured_model_once(predictor_cache,monkeypatch):
    calls=[]
    sentinel=object()
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED","1")
    monkeypatch.setenv("GEOFATHOM_SAM2_MODEL_ID","test-model")
    monkeypatch.setitem(sys.modules,"torch",SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True)))
    module=ModuleType("sam2.sam2_image_predictor")
    module.SAM2ImagePredictor=SimpleNamespace(from_pretrained=lambda name:calls.append(name) or sentinel)
    monkeypatch.setitem(sys.modules,"sam2.sam2_image_predictor",module)
    assert sam._predictor() is sentinel and sam._predictor() is sentinel
    assert calls==["test-model"]
