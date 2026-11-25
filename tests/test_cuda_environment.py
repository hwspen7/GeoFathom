"""Windows DLL discovery and ONNX initialization without NVIDIA hardware."""
from types import SimpleNamespace
import pytest
from core import cuda_environment as env


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("GEOFATHOM_CUDA_BIN", raising=False)
    monkeypatch.delenv("CUDA_PATH", raising=False)
    monkeypatch.setattr(env, "_handles", {})
    monkeypatch.setattr(env, "_preloaded", set())


@pytest.mark.parametrize("subdirectory", ["bin", "bin/x64"])
def test_toolkit_layout(monkeypatch, tmp_path, subdirectory):
    directory = tmp_path / subdirectory
    directory.mkdir(parents=True)
    (directory / "cudart64_13.dll").touch()
    monkeypatch.setenv("CUDA_PATH", str(tmp_path))
    assert env.cuda_bin_directory() == directory.resolve()


def test_override_priority_and_invalid_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("CUDA_PATH", str(tmp_path))
    directory = tmp_path / "custom"
    directory.mkdir()
    monkeypatch.setenv("GEOFATHOM_CUDA_BIN", str(directory))
    with pytest.raises(RuntimeError, match="no CUDA runtime"):
        env.cuda_bin_directory()
    (directory / "cudart64_12.dll").touch()
    assert env.cuda_bin_directory() == directory.resolve()
    monkeypatch.setenv("GEOFATHOM_CUDA_BIN", "relative")
    with pytest.raises(RuntimeError, match="absolute"):
        env.cuda_bin_directory()


def test_preload_once_and_keep_directory_handle(monkeypatch, tmp_path):
    (tmp_path / "cudart64_13.dll").touch()
    monkeypatch.setenv("GEOFATHOM_CUDA_BIN", str(tmp_path))
    monkeypatch.setattr(env, "_is_windows", lambda: True)
    calls = []
    handle = object()
    monkeypatch.setattr(env.os, "add_dll_directory",
                        lambda path: calls.append(path) or handle, raising=False)
    ort = SimpleNamespace(preload_dlls=lambda **kw: calls.append(kw))
    env.prepare_onnx_cuda(ort)
    env.prepare_onnx_cuda(ort)
    assert calls == [
        str(tmp_path.resolve()),
        {"cuda": True, "cudnn": False, "directory": str(tmp_path.resolve())},
        {"cuda": False, "cudnn": True},
    ]
    assert env._handles[tmp_path.resolve()] is handle


def test_no_toolkit_and_non_windows(monkeypatch):
    calls = []
    ort = SimpleNamespace(preload_dlls=lambda **kw: calls.append(kw))
    monkeypatch.setattr(env, "_is_windows", lambda: False)
    assert env.prepare_native_cuda() is None
    env.prepare_onnx_cuda(ort)
    assert calls == []
    monkeypatch.setattr(env, "_is_windows", lambda: True)
    env.prepare_onnx_cuda(ort)
    assert calls == [{}]
    env.prepare_onnx_cuda(SimpleNamespace())  # Older supported ORT versions.


def test_conflicting_runtime_versions_are_rejected(monkeypatch,tmp_path):
    (tmp_path/"cudart64_12.dll").touch()
    (tmp_path/"cudart64_13.dll").touch()
    monkeypatch.setenv("GEOFATHOM_CUDA_BIN",str(tmp_path))
    with pytest.raises(RuntimeError,match="Conflicting CUDA"):
        env.cuda_bin_directory()


def test_loaded_toolkit_cannot_be_switched_in_place(monkeypatch,tmp_path):
    first=tmp_path/"first";second=tmp_path/"second"
    for path in (first,second):
        path.mkdir()
        (path/"cudart64_13.dll").touch()
    monkeypatch.setattr(env,"_is_windows",lambda:True)
    monkeypatch.setattr(env.os,"add_dll_directory",lambda path:object(),raising=False)
    monkeypatch.setenv("GEOFATHOM_CUDA_BIN",str(first))
    env.prepare_native_cuda()
    monkeypatch.setenv("GEOFATHOM_CUDA_BIN",str(second))
    with pytest.raises(RuntimeError,match="restart"):
        env.prepare_native_cuda()
