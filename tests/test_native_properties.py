"""Seeded adversarial differential tests, independent of compiled implementation."""
import os
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pytest
from geometry import spectral
from geometry.transitions import count_transitions

@pytest.mark.parametrize("seed",range(10))
def test_spectral_exact_masks_and_parallel_differential(seed):
    rng=np.random.default_rng(seed)
    a=rng.uniform(-1000,1000,(257,259)).astype(np.float32)
    b=rng.uniform(-1000,1000,a.shape).astype(np.float32)
    mask=rng.integers(0,2,a.shape,dtype=np.uint8)
    a[0,:5]=[0,np.nan,np.inf,np.finfo(np.float32).max,1e-10]
    b[0,:5]=[0,10,3,np.finfo(np.float32).max,-1e-10]
    x,y=a.astype(np.float64),b.astype(np.float64)
    with np.errstate(invalid="ignore",divide="ignore"):
        den=x+y
        valid=(mask!=0)&np.isfinite(x)&np.isfinite(y)&np.isfinite(den)&(np.abs(den)>1e-9)
        expected=np.zeros_like(a)
        np.divide(x-y,den,out=expected,where=valid,casting="unsafe")
        np.clip(expected,-1,1,out=expected)
    result,actual,engine=spectral.normalized_difference(a,b,mask)
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE")=="1":
        assert engine=="cpp-spectral"
    np.testing.assert_array_equal(actual,valid)
    np.testing.assert_array_equal(result,expected)
    labels,_=spectral.classify_change(result,actual,-result,actual,.2)
    delta=-result.astype(np.float64)-result.astype(np.float64)
    ref=np.zeros_like(mask)
    ref[valid&(delta>=np.float32(.2))]=1
    ref[valid&(delta<=-np.float32(.2))]=2
    np.testing.assert_array_equal(labels,ref)

@pytest.mark.parametrize("shape",[(1,1),(1,31),(17,1),(37,19),(255,258),(513,511)])
def test_vectorized_mask_transition_parity(shape):
    rng=np.random.default_rng(138)
    arr=rng.integers(0,32,shape,dtype=np.uint8)
    expected=int(np.count_nonzero(arr[:,1:]!=arr[:,:-1])+np.count_nonzero(arr[1:,:]!=arr[:-1,:]))
    assert count_transitions(arr)==expected
    assert count_transitions(arr[:,::-1])==expected

def test_parallel_native_results_do_not_share_output_buffers():
    def run(i):
        a=np.full((257,257),i+4,np.float32)
        b=np.ones_like(a)
        out,valid,_=spectral.normalized_difference(a,b,np.ones_like(a,np.uint8))
        np.testing.assert_allclose(out,(i+3)/(i+5),rtol=1e-7)
        assert valid.all()
        return out
    with ThreadPoolExecutor(max_workers=8) as workers:
        outputs=list(workers.map(run,range(32)))
    assert all(not np.shares_memory(outputs[0],other) for other in outputs[1:])
