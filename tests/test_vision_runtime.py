"""Model session pool concurrency, eviction and tensor-safety tests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, Thread
import time

import numpy as np
import pytest

from vision.runtime import ModelSessionPool, pool_for, tensor_budget_mb
from vision import semantic as sem
from imagery.raster import RasterError


def test_model_cache_reuses_idle_sessions_and_evicts_lru():
    pool=ModelSessionPool(max_cached=2,max_parallel=2)
    calls=[]
    def create(name):
        calls.append(name)
        return {"model":name}
    with pool.lease("a",lambda:create("a")) as first:
        with pool.lease("a",lambda:create("unused")) as other:
            assert other is first
            assert pool.snapshot()["leased_sessions"]==2
    with pool.lease("b",lambda:create("b")):
        pass
    with pool.lease("a",lambda:create("unused")):
        pass
    with pool.lease("c",lambda:create("c")):
        pass
    assert calls==["a","b","c"]
    assert pool.snapshot()=={
        "cached_sessions":2,"leased_sessions":0,
        "max_cached":2,"max_parallel":2}


def test_pool_never_evicts_an_active_session():
    pool=ModelSessionPool(max_cached=1,max_parallel=2)
    entered=Event()
    released=Event()
    finished=Event()
    names=[]
    def first():
        with pool.lease("a",lambda:object(),timeout=5):
            entered.set()
            assert released.wait(4)
    def second():
        with pool.lease("b",lambda:object(),timeout=5):
            names.append("b")
        finished.set()
    t1=Thread(target=first)
    t2=Thread(target=second)
    t1.start()
    assert entered.wait(4)
    t2.start()
    try:
        assert not finished.wait(.03)
        assert pool.snapshot()["leased_sessions"]==1
    finally:
        released.set()
        t1.join(5)
        t2.join(5)
    assert finished.is_set()
    assert names==["b"]
    assert pool.snapshot()["cached_sessions"]==1


def test_concurrency_gate_and_failed_factory_release_permits():
    pool=ModelSessionPool(max_cached=1,max_parallel=1)
    active=0
    maximum=0
    gate=Lock()
    def runner(_):
        nonlocal active, maximum
        with pool.lease("one",lambda:object(),timeout=5):
            with gate:
                active+=1
                maximum=max(maximum,active)
            time.sleep(.015)
            with gate:
                active-=1
    with ThreadPoolExecutor(max_workers=4) as threads:
        list(threads.map(runner,range(8)))
    assert maximum==1
    def failing():
        raise RuntimeError("Model initialization failed")
    with pytest.raises(RuntimeError,match="initialization"):
        with pool.lease("new",failing):
            pass
    with pool.lease("new",lambda:object()) as session:
        assert session is not None


def test_runtime_config_validations(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_VISION_PARALLEL_INFERENCE","0")
    with pytest.raises(ValueError,match="resource range"):
        pool_for("cpu")
    monkeypatch.setenv("GEOFATHOM_VISION_PARALLEL_INFERENCE","2")
    monkeypatch.setenv("GEOFATHOM_VISION_TENSOR_MEMORY_MB","nan")
    with pytest.raises(ValueError,match="decimal integer"):
        tensor_budget_mb()
    with pytest.raises(ValueError):
        pool_for("unknown")


def test_model_rejects_nonfinite_logits_and_invalid_hard_class_ids(monkeypatch,tmp_path):
    model=tmp_path/"predictions.onnx"
    model.write_bytes(b"mock")
    config={"model_path":model,"tile_size":128,
            "classes":["background","building"]}
    tensor=np.zeros((1,3,128,128),dtype=np.float32)
    class Fake:
        def __init__(self,raw):
            self.raw=raw
        def get_inputs(self):
            return [type("Input",(),{"name":"raster"})()]
        def run(self,_,values):
            return [self.raw]
    raw=np.zeros((1,2,128,128),dtype=np.float32)
    raw[0,0,10,10]=np.nan
    monkeypatch.setattr(sem,"_session",lambda *args:Fake(raw))
    with pytest.raises(RasterError,match="nonfinite"):
        sem._predict_tile(tensor,config,"cpu")
    # Avoid using the cached first fake: a new model file version gets a new
    # session identity and tests that hot reloading cannot reuse old weights.
    model.write_bytes(b"updated weights placeholder")
    invalid=np.full((1,128,128),-1,dtype=np.int64)
    monkeypatch.setattr(sem,"_session",lambda *args:Fake(invalid))
    with pytest.raises(RasterError,match="class IDs"):
        sem._predict_tile(tensor,config,"cpu")
    monkeypatch.setenv("GEOFATHOM_VISION_TENSOR_MEMORY_MB","8")
    with pytest.raises(RasterError,match="tensor memory"):
        sem._predict_tile(np.zeros((1,3,512,512),dtype=np.float32),
                          {**config,"tile_size":512,"classes":list(range(32))},
                          "cpu")


def test_cuda_io_binding_dispatch_with_mocked_onnx_session(monkeypatch,tmp_path):
    from vision import semantic
    model=tmp_path/"io.onnx"
    model.write_bytes(b"only a mocked provider, no model weights")
    monkeypatch.setenv("GEOFATHOM_VISION_IO_BINDING","1")
    steps=[]
    output=np.zeros((1,2,128,128),dtype=np.float32)
    output[:,1]=3
    class Bound:
        def bind_cpu_input(self,name,tensor):
            steps.append(("input",name,tensor.shape))
        def bind_output(self,name,device):
            steps.append(("output",name,device))
        def copy_outputs_to_cpu(self):
            steps.append(("transfer","cpu"))
            return [output]
    class Fake:
        def get_inputs(self):
            return [type("Input",(),{"name":"source"})()]
        def get_outputs(self):
            return [type("Output",(),{"name":"classes"})()]
        def io_binding(self):
            return Bound()
        def run_with_iobinding(self,binding):
            steps.append(("run","cuda"))
        def run(self,*args):
            raise AssertionError("CUDA I/O binding path must not call run()")
    monkeypatch.setattr(semantic,"_session",lambda *args:Fake())
    config={"model_path":model,"tile_size":128,"classes":["background","building"]}
    labels,confidence=semantic._predict_tile(
        np.zeros((1,3,128,128),dtype=np.float32),config,"cuda")
    assert np.all(labels==1)
    assert np.all(confidence>.9)
    assert steps==[
        ("input","source",(1,3,128,128)),
        ("output","classes","cuda"),
        ("run","cuda"),("transfer","cpu"),
    ]


def test_real_gpu_acceptance_requires_operator_installed_model(monkeypatch):
    import os
    from pathlib import Path
    from vision import semantic
    identifier=os.getenv("GEOFATHOM_GPU_ACCEPTANCE_MODEL")
    if not identifier:
        pytest.skip("Configure a real ONNX model and CUDA hardware to run GPU acceptance.")
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE","cuda")
    monkeypatch.setenv("GEOFATHOM_VISION_IO_BINDING","1")
    config=semantic._manifest(identifier)
    size=config["tile_size"]
    tensor=np.zeros((1,3,size,size),dtype=np.float32)
    start=time.perf_counter()
    for _ in range(10):
        labels,confidence=semantic._predict_tile(tensor,config,"cuda")
        assert labels.shape==(size,size)
        assert np.isfinite(confidence).all()
    elapsed=time.perf_counter()-start
    print(f"10 real ONNX CUDA inference passes: {elapsed:.3f}s")
    assert elapsed>0
