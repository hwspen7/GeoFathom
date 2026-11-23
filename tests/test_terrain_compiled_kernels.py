"""Numerical equivalence and bounded-memory CPU acceptance for JIT D-infinity."""
from threading import Event
from time import perf_counter
import os

import numpy as np
import psutil
import pytest

from terrain.cancellation import TerrainCancelled
from terrain.scientific_kernels import dinfinity_accumulation


@pytest.mark.parametrize("dx,dy",[(1,1),(5,20),(20,5)])
def test_compiled_flow_is_identical_to_independent_python_routing_reference(dx,dy):
    rng=np.random.default_rng(1001+dx+dy)
    y,x=np.indices((18,23))
    # Monotone global descent with local waves and a masked internal gap.
    z=1000.-.2*x-.3*y+.02*np.sin(x/2)+.03*np.cos(y/3)
    mask=np.ones(z.shape,bool);mask[5:7,9:11]=False
    external=np.zeros(z.shape);external[0,0]=100
    fast,angle=dinfinity_accumulation(z,mask,dx,dy,external_inflow=external)
    slow,reference_angle=dinfinity_accumulation(z,mask,dx,dy,
        external_inflow=external,compiled=False)
    np.testing.assert_allclose(fast,slow,rtol=1e-12,atol=1e-10,equal_nan=True)
    np.testing.assert_allclose(angle,reference_angle,rtol=0,atol=1e-11,equal_nan=True)
    assert np.isfinite(fast[mask]).all()


def test_production_dinfinity_compiled_routing_has_hard_cpu_and_memory_budget():
    # Warm the compiler before measuring *per-request* scientific latency.
    trivial=np.arange(64.,0.,-1.)[None,:].repeat(64,axis=0)
    dinfinity_accumulation(trivial,np.ones(trivial.shape,bool),10,10)
    n=512
    y,x=np.indices((n,n))
    z=1000.-.2*x-.1*y
    valid=np.ones(z.shape,bool)
    process=psutil.Process(os.getpid())
    before=process.memory_info().rss
    started=perf_counter()
    acc,_=dinfinity_accumulation(z,valid,10,10)
    elapsed=perf_counter()-started
    delta=max(0,process.memory_info().rss-before)
    assert acc[-1,-1]==pytest.approx(n*n,abs=1e-5)
    assert elapsed<6.,f"Compiled 262k-cell D-infinity exceeded 6 s: {elapsed:.3f} s"
    assert delta<256*1024*1024,f"D-infinity exceeded 256 MiB RSS growth: {delta}"
    assert np.isfinite(acc).all()


def test_cancellation_prevents_partial_compiled_flow_results():
    flag=Event();flag.set()
    z=np.arange(128.,0.,-1.)[None,:].repeat(128,axis=0)
    with pytest.raises(TerrainCancelled):
        dinfinity_accumulation(z,np.ones(z.shape,bool),10,10,cancel=flag)
