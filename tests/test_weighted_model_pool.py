from threading import Event,Thread
from concurrent.futures import ThreadPoolExecutor
import pytest
from vision.runtime import ModelSessionPool

def test_memory_admission_evicts_multiple_idle_models():
    pool=ModelSessionPool(4,2,1000)
    for name in ("a","b","c"):
        with pool.lease(name,object,reserved_bytes=280,working_bytes=10):pass
    assert pool.reservations()["cached_bytes"]==840
    with pool.lease("d",object,reserved_bytes=650,working_bytes=50):
        assert pool.reservations()=={"cached_bytes":930,"active_working_bytes":50,"budget_bytes":1000}
    with pytest.raises(MemoryError):
        with pool.lease("huge",object,reserved_bytes=1001):pass

def test_active_models_wait_and_memory_reservation_released_on_failure():
    pool=ModelSessionPool(3,3,100)
    entered=Event();released=Event()
    def task():
        with pool.lease("a",object,reserved_bytes=60,working_bytes=30):
            entered.set();assert released.wait(5)
    with ThreadPoolExecutor(max_workers=2) as workers:
        run=workers.submit(task)
        assert entered.wait(3)
        try:
            with pytest.raises(RuntimeError,match="capacity"):
                with pool.lease("b",object,timeout=.05,reserved_bytes=40,working_bytes=20):pass
            assert pool.reservations()["active_working_bytes"]==30
        finally:
            released.set()
        run.result(5)
    def failed():raise RuntimeError("OOM")
    with pytest.raises(RuntimeError,match="OOM"):
        with pool.lease("b",failed,reserved_bytes=60,working_bytes=40):pass
    assert pool.reservations()["active_working_bytes"]==0
    with pool.lease("c",object,reserved_bytes=60,working_bytes=40):
        assert pool.reservations()["active_working_bytes"]==40
    assert pool.reservations()["active_working_bytes"]==0
