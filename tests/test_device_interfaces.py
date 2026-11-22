"""Exercise Python CUDA ABI contracts without requiring a device in hosted CI.

The fake buffers exercise validation and pointer transport, not CUDA kernels.
Native device correctness is independently covered by the hardware CTest.
"""
import ctypes
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest

from geometry import device_arrays as arrays, topology
from imagery.raster import RasterError
from vision.device_postprocess import decode_cuda_logits


class FakeArray:
    def __init__(self, shape=(2, 3), dtype="float32", device=0, contiguous=True):
        self.shape = shape
        self.size = int(np.prod(shape))
        self.ndim = len(shape)
        self.dtype = np.dtype(dtype)
        self.device = SimpleNamespace(id=device)
        self.flags = SimpleNamespace(c_contiguous=contiguous)
        self.data = SimpleNamespace(ptr=id(self))


@pytest.fixture
def cupy_backend(monkeypatch):
    calls = []

    def index(device, a, b, valid, count, output, mask):
        calls.append(("index", device, a, b, valid, count, output, mask))
        return 0

    def change(device, a, av, b, bv, count, threshold, output):
        calls.append(("change", device, a, av, b, bv, count, threshold, output))
        return 0

    lib = SimpleNamespace(gf_cuda_device_index=index, gf_cuda_device_change=change)
    cp = SimpleNamespace(ndarray=FakeArray, dtype=np.dtype, float32=np.float32,
                         uint8=np.uint8, empty=lambda shape, dtype: FakeArray(shape, dtype),
                         cuda=SimpleNamespace(Device=lambda _: nullcontext()))
    monkeypatch.setitem(sys.modules, "cupy", cp)
    monkeypatch.setattr(topology, "_native", lambda: lib)
    return lib, calls


def test_device_array_pointer_and_type_contract(cupy_backend):
    lib, calls = cupy_backend
    a, b, valid = FakeArray(), FakeArray(), FakeArray(dtype="uint8")
    out, mask = arrays.normalized_difference(a, b, valid)
    result = arrays.classify_change(out, mask, b, valid, .25)
    assert out.dtype == np.float32 and mask.dtype == result.dtype == np.uint8
    assert calls == [
        ("index", 0, a.data.ptr, b.data.ptr, valid.data.ptr, 6, out.data.ptr, mask.data.ptr),
        ("change", 0, out.data.ptr, mask.data.ptr, b.data.ptr, valid.data.ptr, 6, .25, result.data.ptr),
    ]
    assert lib.gf_cuda_device_index.restype is ctypes.c_int


@pytest.mark.parametrize("invalid", [
    FakeArray(shape=(6,)), FakeArray(dtype="float64"), FakeArray(device=1),
    FakeArray(contiguous=False), FakeArray(shape=(3, 2)),
])
def test_device_array_rejects_incompatible_inputs(cupy_backend, invalid):
    with pytest.raises(ValueError):
        arrays.normalized_difference(FakeArray(), invalid, FakeArray(dtype="uint8"))
    assert cupy_backend[1] == []


def test_device_array_rejects_host_pointer_and_missing_backend(cupy_backend, monkeypatch):
    a, v = FakeArray(), FakeArray(dtype="uint8")
    with pytest.raises(TypeError):
        arrays.normalized_difference(np.ones((2, 3)), a, v)
    with pytest.raises(ValueError):
        arrays.classify_change(a, v, a, v, float("nan"))
    monkeypatch.setattr(topology, "_native", lambda: None)
    with pytest.raises(RuntimeError, match="not installed"):
        arrays.normalized_difference(a, a, v)


def test_device_array_propagates_native_failure(cupy_backend):
    lib, _ = cupy_backend
    def fail(*args):
        return -1
    lib.gf_cuda_device_index = fail
    lib.gf_cuda_device_change = fail
    a, v = FakeArray(), FakeArray(dtype="uint8")
    with pytest.raises(RuntimeError, match="index failed"):
        arrays.normalized_difference(a, a, v)
    with pytest.raises(RuntimeError, match="change failed"):
        arrays.classify_change(a, v, a, v, .25)


class FakeOrtValue:
    def __init__(self, shape, dtype, device="cuda", payload=None):
        self._shape, self._dtype, self._device = shape, dtype, device
        self.payload = payload

    def shape(self):
        return self._shape

    def data_type(self):
        return self._dtype

    def device_name(self):
        return self._device

    def data_ptr(self):
        return id(self)

    def numpy(self):
        assert self.payload is not None, "Input logits must not be copied to host"
        return self.payload


@pytest.fixture
def ort_backend(monkeypatch):
    allocated, calls = [], []
    def allocate(shape, dtype, device, device_id):
        assert device == "cuda" and device_id == 0
        arr = np.full(shape, 1 if dtype == np.uint8 else .75, dtype=dtype)
        value = FakeOrtValue(shape, str(dtype), payload=arr)
        allocated.append(value)
        return value

    def decode(*args):
        calls.append(args)
        return 0

    lib = SimpleNamespace(gf_cuda_device_semantic=decode)
    monkeypatch.setattr(topology, "_native", lambda: lib)
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        OrtValue=SimpleNamespace(ortvalue_from_shape_and_type=allocate)))
    return lib, allocated, calls


@pytest.mark.parametrize("dtype,shape,kind", [
    ("tensor(float)", (1, 2, 2, 2), 0),
    ("tensor(int64)", (1, 2, 2), 1),
    ("tensor(int32)", (1, 2, 2), 2),
    ("tensor(uint8)", (1, 2, 2), 3),
])
def test_gpu_decode_abi_and_compact_outputs(ort_backend, dtype, shape, kind):
    _, allocated, calls = ort_backend
    value = FakeOrtValue(shape, dtype)
    labels, confidence = decode_cuda_logits(value, 1, 2, 2, 0)
    assert np.all(labels == 1) and np.all(confidence == .75)
    assert calls == [(0, value.data_ptr(), 1, 4, 2, kind,
                      allocated[0].data_ptr(), allocated[1].data_ptr())]


@pytest.mark.parametrize("value", [
    FakeOrtValue((1, 2, 2, 2), "tensor(float)", "cpu"),
    FakeOrtValue((1, 2, 2, 2), "tensor(double)"),
    FakeOrtValue((1, 3, 2, 2), "tensor(float)"),
])
def test_gpu_decode_rejects_invalid_metadata(ort_backend, value):
    with pytest.raises(RasterError):
        decode_cuda_logits(value, 1, 2, 2, 0)
    assert ort_backend[1] == []


def test_gpu_decode_rejects_invalid_native_output(ort_backend):
    lib, allocated, _ = ort_backend
    def invalid(*args):
        allocated[1].payload.fill(np.nan)
        return 0
    lib.gf_cuda_device_semantic = invalid
    value = FakeOrtValue((1, 2, 2, 2), "tensor(float)")
    with pytest.raises(RasterError, match="nonfinite"):
        decode_cuda_logits(value, 1, 2, 2, 0)
    def fail(*args):
        return -1
    lib.gf_cuda_device_semantic = fail
    with pytest.raises(RuntimeError, match="postprocessing failed"):
        decode_cuda_logits(value, 1, 2, 2, 0)


def test_gpu_decode_missing_native_backend(ort_backend, monkeypatch):
    monkeypatch.setattr(topology, "_native", lambda: None)
    with pytest.raises(RuntimeError, match="unavailable"):
        decode_cuda_logits(FakeOrtValue((1, 2, 2, 2), "tensor(float)"), 1, 2, 2, 0)
