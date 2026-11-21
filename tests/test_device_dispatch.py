import numpy as np
import pytest
from geometry import spectral

def test_auto_cpu_fallback_matches_reference(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE","auto")
    monkeypatch.setenv("GEOFATHOM_CUDA_MIN_PIXELS","1")
    a=np.full((17,19),200,np.float32);b=np.full_like(a,50)
    valid=np.ones_like(a,np.uint8)
    result,mask,engine=spectral.normalized_difference(a,b,valid)
    assert engine in ("cpp-spectral","numpy-spectral","cuda-spectral")
    np.testing.assert_allclose(result,.6)
    assert mask.all()
    labels,overlap,actual,index_engines=spectral.paired_change(
        (a,b),valid,(b,a),valid,.25)
    assert np.all(labels==2) and overlap.all()
    assert len(index_engines)==2

def test_strict_cuda_unavailable_is_not_silently_fallback(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_SPECTRAL_DEVICE","cuda")
    monkeypatch.setattr(spectral,"_native",lambda:None)
    values=np.ones((2,2),np.float32)
    with pytest.raises(RuntimeError,match="CUDA"):
        spectral.normalized_difference(values,values,values)

def test_automatic_cuda_failure_retries_cpu(monkeypatch):
    class Function:
        def __call__(self,*args):return 0
    class Fake:
        gf_spectral_normalized_difference=Function()
        gf_cuda_runtime_create=Function()
    lib=Fake()
    monkeypatch.setattr(spectral,"cuda_handle",lambda *args: (_ for _ in ()).throw(RuntimeError("allocation")))
    monkeypatch.setattr(spectral,"runtime_handle",lambda *args:None)
    result=spectral._native_kernel(lib,"gf_spectral_normalized_difference",
        "gf_cpu_runtime_index","gf_cuda_runtime_index",1,[],(),"cuda",True)
    assert result=="cpp-spectral"
    with pytest.raises(RuntimeError,match="allocation"):
        spectral._native_kernel(lib,"gf_spectral_normalized_difference",
            "gf_cpu_runtime_index","gf_cuda_runtime_index",1,[],(),"cuda",False)
