"""Process-local CUDA DLL discovery for Windows native and ONNX execution.

Only operator-configured absolute directories are registered. DLL directory
handles stay alive for the life of the interpreter, including spawned workers.
Linux/macOS retain their normal dynamic linker configuration.
"""
import os
import sys
from pathlib import Path
from threading import RLock

_lock = RLock()
_handles = {}
_preloaded = set()


def _is_windows():
    return sys.platform == "win32"


def _absolute_directory(raw, variable):
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise RuntimeError(f"{variable} must identify an existing absolute directory.")
    return path.resolve()


def _runtime_names(path):
    return {p.name.lower() for p in path.glob("cudart64_*.dll") if p.is_file()}


def _validate_runtime(directory):
    names = _runtime_names(directory)
    if len(names) > 1:
        raise RuntimeError("Conflicting CUDA runtime DLL versions in the same directory.")
    return bool(names)


def cuda_bin_directory():
    """Prefer an explicit override; otherwise inspect the active toolkit only."""
    override = os.getenv("GEOFATHOM_CUDA_BIN")
    if override:
        path = _absolute_directory(override, "GEOFATHOM_CUDA_BIN")
        if not _validate_runtime(path):
            raise RuntimeError("GEOFATHOM_CUDA_BIN contains no CUDA runtime DLL.")
        return path
    root = os.getenv("CUDA_PATH")
    if not root:
        return None
    path = Path(root).expanduser()
    if not path.is_absolute() or not path.is_dir():
        return None
    # CUDA 13 uses bin/x64 on Windows; earlier releases use bin.
    candidates = [p.resolve() for p in (path / "bin" / "x64", path / "bin")
                  if p.is_dir() and _validate_runtime(p)]
    if len(set().union(*[_runtime_names(p) for p in candidates])) > 1:
        raise RuntimeError("Active CUDA toolkit contains conflicting runtime versions.")
    return candidates[0] if candidates else None


def prepare_native_cuda():
    """Register the toolkit directory before ctypes loads a native DLL."""
    if not _is_windows():
        return None
    directory = cuda_bin_directory()
    if directory is not None:
        with _lock:
            # A loaded CUDA runtime cannot safely be switched in-place.
            if _handles and directory not in _handles:
                raise RuntimeError("CUDA toolkit changed after initialization; restart the process.")
            if directory not in _handles:
                _handles[directory] = os.add_dll_directory(str(directory))
    return directory


def prepare_onnx_cuda(ort):
    """Preload matching CUDA/cuDNN libraries when the ORT API supports it.

    Wheel-provided libraries remain supported when no toolkit is configured.
    Session creation still verifies that the requested CUDA EP is active.
    """
    if not _is_windows():
        return
    directory = prepare_native_cuda()
    preload = getattr(ort, "preload_dlls", None)
    if preload is None:
        return
    key = (id(ort), directory)
    with _lock:
        if key in _preloaded:
            return
        if directory is not None:
            preload(cuda=True, cudnn=False, directory=str(directory))
            preload(cuda=False, cudnn=True)
        else:
            preload()
        _preloaded.add(key)
