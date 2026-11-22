"""Numerical parity and failure contracts without requiring GPU hardware."""
from types import SimpleNamespace
import numpy as np
import pytest
from geometry import spectral
from terrain import engine
from imagery.raster import RasterError

@pytest.fixture
def bands():
    a=np.array([[3,1],[0,2]],np.float32)
    b=np.array([[1,3],[0,2]],np.float32)
    valid=np.ones((2,2),np.uint8)
    return a,b,valid

def test_numpy_spectral_preserves_masks_and_change_classes(monkeypatch,bands):
    a,b,valid=bands
    monkeypatch.setattr(spectral,"_native",lambda:None)
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE","cpu")
    result,mask,implementation=spectral.normalized_difference(a,b,valid)
    np.testing.assert_array_equal(mask,[[1,1],[0,1]])
    np.testing.assert_allclose(result,[[.5,-.5],[0,0]])
    labels,usable,implementation,engines=spectral.paired_change((a,b),valid,(b,a),valid,.2)
    np.testing.assert_array_equal(labels,[[2,1],[0,0]])
    np.testing.assert_array_equal(usable,mask)
    assert implementation=="numpy-spectral" and engines==["numpy-spectral"]*2

@pytest.mark.parametrize("mode,minimum,expected",[
    ("cpu","1",("cpu",False)),
    ("auto","5",("cpu",True)),
    ("auto","4",("cuda",True)),
    ("cuda","1",("cuda",False))])
def test_spectral_dispatch_policy(monkeypatch,mode,minimum,expected):
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE",mode)
    monkeypatch.setenv("GEOFATHOM_CUDA_MIN_PIXELS",minimum)
    assert spectral._requested_device(SimpleNamespace(gf_cuda_runtime_create=True),4)==expected

@pytest.mark.parametrize("mode,minimum,exception",[
    ("unknown","1",ValueError),("auto","0",ValueError),("cuda","1",RuntimeError)])
def test_spectral_invalid_device_policy(monkeypatch,mode,minimum,exception):
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE",mode)
    monkeypatch.setenv("GEOFATHOM_CUDA_MIN_PIXELS",minimum)
    with pytest.raises(exception):spectral._requested_device(None,4)

def test_auto_cuda_failure_retries_cpu_but_explicit_cuda_fails(monkeypatch,bands):
    a,b,valid=bands
    native=spectral._native()
    assert native is not None or not __import__("os").getenv("GEOFATHOM_REQUIRE_NATIVE")
    def fail(*args):raise MemoryError("device allocation rejected")
    # Use the real CPU kernel for the fallback whenever installed.
    if native is None:
        # Only this dispatch contract uses an injected CPU kernel.
        def cpu(*args):
            out,mask=args[-2:]
            np.ctypeslib.as_array(out,shape=(4,))[:]=[.5,-.5,0,0]
            np.ctypeslib.as_array(mask,shape=(4,))[:]=[1,1,0,1]
            return 3
    else:
        def cpu(*args):return native.gf_spectral_normalized_difference(*args)
        import ctypes
        native.gf_spectral_normalized_difference.argtypes=[ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_uint8),ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_uint8)]
        native.gf_spectral_normalized_difference.restype=ctypes.c_int
    lib=SimpleNamespace(gf_cuda_runtime_create=True,gf_spectral_normalized_difference=cpu)
    monkeypatch.setattr(spectral,"_native",lambda:lib)
    monkeypatch.setattr(spectral,"runtime_handle",lambda _:None)
    monkeypatch.setattr(spectral,"cuda_handle",fail)
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE","auto")
    monkeypatch.setenv("GEOFATHOM_CUDA_MIN_PIXELS","1")
    result,mask,name=spectral.normalized_difference(a,b,valid)
    assert name=="cpp-spectral"
    np.testing.assert_allclose(result,[[.5,-.5],[0,0]])
    np.testing.assert_array_equal(mask,[[1,1],[0,1]])
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE","cuda")
    with pytest.raises(MemoryError,match="allocation"):spectral.normalized_difference(a,b,valid)

@pytest.mark.parametrize("threshold",[True,0,1,float("nan"),"0.2"])
def test_paired_change_rejects_invalid_threshold(bands,threshold):
    a,b,valid=bands
    with pytest.raises(ValueError):spectral.paired_change((a,b),valid,(b,a),valid,threshold)

def test_terrain_numpy_horn_matches_native_and_handles_flat_mask(monkeypatch):
    z=np.tile(np.arange(8,dtype=np.float32)*10,(8,1))
    valid=np.ones_like(z,dtype=bool)
    native=engine._native_slope(z,valid,10,10)
    monkeypatch.setattr(engine,"_native",lambda:None)
    fallback=engine._native_slope(z,valid,10,10)
    assert fallback["mean_slope_deg"]==pytest.approx(45)
    assert fallback["mean_aspect_deg"]==pytest.approx(270)
    assert fallback["gradient_pixels"]==36
    for key in ("mean_slope_deg","mean_aspect_deg","maximum_slope_deg","gradient_pixels"):
        assert fallback[key]==pytest.approx(native[key],abs=1e-5)
    flat=engine._native_slope(np.ones_like(z),valid,10,10)
    assert flat["mean_aspect_deg"] is None and flat["mean_slope_deg"]==0
    with pytest.raises(RasterError,match="no valid"):
        engine._native_slope(z,np.zeros_like(valid),10,10)
