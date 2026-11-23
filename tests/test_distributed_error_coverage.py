"""Coordinator error-path and lease-fencing coverage without a live broker.

PostgreSQL integration tests cover successful remote operation. These tests
exercise rejection, lost-lease and cancellation paths independently.
"""
from types import SimpleNamespace

import pytest

from jobs import distributed


@pytest.mark.parametrize("queue",["","bad name","/"*10,"x"*65,None])
def test_distributed_queue_identifiers_are_rejected_before_connection(queue):
    with pytest.raises(ValueError,match="queue name"):
        distributed.Broker("postgresql://unused",queue)


def _broker_without_postgres():
    broker=distributed.Broker.__new__(distributed.Broker)
    broker.queue="test-queue"
    broker.dsn="postgresql://unused"
    return broker


def test_broker_rejects_ineligible_task_before_opening_database():
    broker=_broker_without_postgres()
    with pytest.raises(ValueError,match="pure local raster"):
        broker.submit({"kind":"export_geojson"})
    with pytest.raises(ValueError,match="too large"):
        broker.submit({"kind":"spectral_index","padding":"a"*110000})
    with pytest.raises(ValueError,match="compute node identifier"):
        broker.claim("node/with/a/slash")
    for value in (0,-1,3651,True,1.5):
        with pytest.raises(ValueError,match="retention"):
            broker.prune(value)


def test_distributed_broker_requires_explicit_postgres_and_shared_archive(monkeypatch):
    monkeypatch.delenv("GEOFATHOM_DISTRIBUTED_DSN",raising=False)
    monkeypatch.delenv("GEOFATHOM_VERSION_DIR",raising=False)
    with pytest.raises(RuntimeError,match="DSN"):
        distributed.configured_broker()
    with pytest.raises(RuntimeError,match="shared GEOFATHOM_VERSION_DIR"):
        distributed.dispatch("spectral_index",{},{"source_sha256":{}},lambda _:None)


@pytest.mark.parametrize("terminal,expect_failure",[
    ({"status":"completed","result":{"valid_pixels":5}},False),
    ({"status":"failed","error":"Remote GDAL error"},True),
    ({"status":"cancelled","error":None},True),
])
def test_distributed_dispatch_preserves_remote_terminal_state(
    monkeypatch,tmp_path,terminal,expect_failure,
):
    monkeypatch.setenv("GEOFATHOM_VERSION_DIR",str(tmp_path))
    captures={"cancel":[],"progress":[]}
    class Broker:
        def submit(self,spec):
            assert spec["kind"]=="spectral_index"
            assert spec["payload"]=={"image_id":"unit"}
            return "task","token"
        def poll(self,uid,token):
            assert (uid,token)==("task","token")
            return terminal
        def cancel(self,*args):captures["cancel"].append(args)
    monkeypatch.setattr(distributed,"archive_inputs",lambda root,provenance:None)
    monkeypatch.setattr(distributed,"configured_broker",lambda:Broker())
    provenance={"source_sha256":{},"model_files_sha256":{}}
    if expect_failure:
        with pytest.raises(RuntimeError,match="Remote GDAL error|did not complete"):
            distributed.dispatch("spectral_index",{"image_id":"unit"},provenance,
                captures["progress"].append)
    else:
        assert distributed.dispatch("spectral_index",{"image_id":"unit"},provenance,
                                   captures["progress"].append)=={"valid_pixels":5}
        assert captures["progress"]==[1.]
    assert captures["cancel"]==[("task","token")]


def test_dispatch_aborts_on_remote_timeout_and_tolerates_failed_cancellation(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_VERSION_DIR",str(tmp_path))
    monkeypatch.setattr(distributed,"archive_inputs",lambda root,provenance:None)
    class Broker:
        cancelled=0
        def submit(self,spec):return "task","token"
        def poll(self,*args):return {"status":"running"}
        def cancel(self,*args):
            self.cancelled+=1
            raise ConnectionError("Simulated database outage")
    broker=Broker()
    monkeypatch.setattr(distributed,"configured_broker",lambda:broker)
    ticks=iter([0.,90.])
    monkeypatch.setattr(distributed.time,"monotonic",lambda:next(ticks))
    monkeypatch.setattr(distributed,"_limit",lambda *args:30)
    with pytest.raises(RuntimeError,match="timed out"):
        distributed.dispatch("spectral_index",{},{"source_sha256":{}},lambda _:None)
    assert broker.cancelled==1


def test_dispatch_reports_running_progress_then_completion(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_VERSION_DIR",str(tmp_path))
    monkeypatch.setattr(distributed,"archive_inputs",lambda *args:None)
    class Broker:
        items=iter([{"status":"queued"},{"status":"running"},
                    {"status":"completed","result":{"ok":True}}])
        def submit(self,spec):return "task","token"
        def poll(self,*args):return next(self.items)
        def cancel(self,*args):pass
    monkeypatch.setattr(distributed,"configured_broker",lambda:Broker())
    monkeypatch.setattr(distributed.time,"sleep",lambda *_:None)
    values=[]
    assert distributed.dispatch("spectral_index",{},{"source_sha256":{}},values.append)=={"ok":True}
    assert values==[.2,.2,1.]


def test_remote_child_rejects_unsupported_compute_before_reading_snapshots(
    monkeypatch,tmp_path,
):
    import json
    from jobs import hard_limits,resources
    monkeypatch.setattr(hard_limits,"enforce",lambda *args:None)
    monkeypatch.setattr(resources,"configure_child",lambda *args:None)
    payload={"kind":"export_geojson","payload":{},"provenance":{
        "source_sha256":{},"model_files_sha256":{}}}
    class Pipe:
        result=None;closed=False
        def send_bytes(self,data):self.result=json.loads(data)
        def close(self):self.closed=True
    pipe=Pipe()
    distributed._remote_child(pipe,payload,str(tmp_path),str(tmp_path))
    assert pipe.result["status"]=="error"
    assert "Unsupported remote computation" in pipe.result["error"]
    assert pipe.closed


def test_remote_worker_idle_returns_without_spawning():
    assert distributed.worker_once(SimpleNamespace(claim=lambda _:None),
                                   "idle-node","/nonexistent")==False


def test_distributed_cli_pruning_does_not_start_worker_loop(monkeypatch,capsys):
    import sys
    calls=[]
    monkeypatch.setattr(sys,"argv",["gf-remote","--node","unit","--cleanup-days","14"])
    monkeypatch.setattr(distributed,"configured_broker",
                        lambda:SimpleNamespace(prune=lambda days:calls.append(days) or 7))
    distributed.main()
    assert calls==[14]
    assert "Removed 7 terminal broker tasks" in capsys.readouterr().out
