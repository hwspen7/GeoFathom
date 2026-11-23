"""Isolation supervision and bounded IPC tests without child-process stubs in production.

The envelope, cleanup, context restoration, and budget controls must remain
safe under malformed results and non-cooperative worker termination.
"""
import json
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest

from jobs import isolation, queue
from storage.database import StorageError


class FakePipe:
    def __init__(self,data=b""):
        self.data=data
        self.closed=False
        self.sent=[]
    def recv_bytes(self,maxlength=None):
        if isinstance(self.data,Exception):raise self.data
        return self.data
    def send_bytes(self,content):
        self.sent.append(json.loads(content))
    def close(self):self.closed=True


@pytest.mark.parametrize("data,expected",[
    (b"[]","invalid envelope"),
    (b"{}","invalid envelope"),
    (b'{"status":"ok"}',"invalid envelope"),
    (b'{"status":"error","error":"real native error"}',"real native error"),
    (b"not json","IPC closed"),
])
def test_ipc_envelope_never_accepts_bad_or_partial_messages(data,expected):
    with pytest.raises(RuntimeError,match=expected):
        isolation._read_result(FakePipe(data))


def test_ipc_envelope_accepts_json_null_and_structured_results():
    assert isolation._read_result(FakePipe(b'{"status":"ok","result":null}')) is None
    assert isolation._read_result(FakePipe(b'{"status":"ok","result":{"rows":[1,2]}}'))=={"rows":[1,2]}
    with pytest.raises(RuntimeError,match="IPC closed"):
        isolation._read_result(FakePipe(EOFError()))


def test_result_reader_reports_not_ready_and_propagates_worker_errors():
    start=Event();release=Event()
    class Suspended(FakePipe):
        def recv_bytes(self,maxlength=None):
            start.set()
            assert release.wait(5)
            return self.data
    pipe=Suspended(b'{"status":"ok","result":[1,2]}')
    reader=isolation.ResultReader(pipe)
    assert start.wait(5)
    with pytest.raises(RuntimeError,match="not ready"):
        reader.get()
    release.set()
    assert reader.ready.wait(5)
    assert reader.get()==[1,2]
    bad=isolation.ResultReader(FakePipe(b'{"status":"error","error":"failed"}'))
    assert bad.ready.wait(5)
    with pytest.raises(RuntimeError,match="failed"):bad.get()


@pytest.mark.parametrize("stubborn,expected_terminates,expected_kills",[
    (False,1,0),(True,1,1),
])
def test_terminate_escalates_only_when_cooperative_termination_fails(stubborn,expected_terminates,expected_kills):
    class Process:
        alive=True;terminations=0;kills=0
        def is_alive(self):return self.alive
        def terminate(self):
            self.terminations+=1
            if not stubborn:self.alive=False
        def kill(self):self.kills+=1;self.alive=False
        def join(self,timeout):assert timeout==3
    process=Process()
    isolation._terminate(process)
    assert process.terminations==expected_terminates
    assert process.kills==expected_kills


def test_cleanup_closes_pipe_even_when_terminator_raises(monkeypatch):
    process=SimpleNamespace(pid=123,close=lambda:None)
    receive=FakePipe();send=FakePipe()
    def fail(_):raise RuntimeError("Cannot terminate")
    monkeypatch.setattr(isolation,"_terminate",fail)
    with pytest.raises(RuntimeError,match="Cannot terminate"):
        isolation.cleanup_child(process,receive,send,None)
    assert receive.closed and send.closed


def test_cleanup_drains_reader_before_closing_receiving_pipe(monkeypatch):
    order=[]
    class Process:
        pid=123
        def is_alive(self):return False
        def join(self,timeout):order.append("process.join")
        def close(self):order.append("process.close")
    class Pipe:
        def close(self):order.append("pipe.close")
    reader=SimpleNamespace(thread=SimpleNamespace(join=lambda timeout:order.append("reader.join")))
    isolation.cleanup_child(Process(),Pipe(),Pipe(),reader)
    assert order==["process.join","process.close","pipe.close","reader.join","pipe.close"]


@pytest.mark.parametrize("result,error,expected",[
    ({"id":42},None,"ok"),(None,"GDAL failed","error"),
    ({"huge":"x"*5_000_110},None,"error"),
])
def test_spawned_child_envelope_bounds_and_context_cleanup(
    monkeypatch,tmp_path,result,error,expected,
):
    from jobs import hard_limits,resources
    path=tmp_path/"isolation-test.sqlite"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE gis_job_slots(name TEXT,owner TEXT)")
        c.execute("INSERT INTO gis_job_slots VALUES ('compute:9','test-owner')")
    calls=[]
    monkeypatch.setattr(hard_limits,"enforce",lambda key:calls.append(("enforce",key)))
    monkeypatch.setattr(resources,"configure_child",lambda slot:calls.append(("slot",slot)))
    def execute(kind,project_id,payload):
        assert (kind,project_id,payload)==("export_geojson","project",{})
        if error:raise RuntimeError(error)
        return result
    monkeypatch.setattr(queue,"_execute",execute)
    send=FakePipe()
    prior=(queue._ACTIVE_JOB.get(),queue._ACTIVE_OWNER.get(),queue._ACTIVE_PROGRESS.get())
    isolation._child_entry(send,str(path),"unit-task","test-owner",
                           "export_geojson","project",{},str(tmp_path/"scratch"))
    assert len(send.sent)==1
    assert send.sent[0]["status"]==expected
    if error:assert error in send.sent[0]["error"]
    if result and "huge" in result:assert "5 MB" in send.sent[0]["error"]
    if expected=="ok":assert send.sent[0]["result"]==result
    assert ("slot",9) in calls
    assert send.closed
    assert (queue._ACTIVE_JOB.get(),queue._ACTIVE_OWNER.get(),queue._ACTIVE_PROGRESS.get())==prior


def test_isolation_root_creates_and_removes_temporary_worker_directory(monkeypatch,tmp_path):
    root=tmp_path/"sandbox"
    monkeypatch.setenv("GEOFATHOM_SNAPSHOT_DIR",str(root))
    observed=[]
    def execute(*args):
        scratch=args[-1]
        observed.append(scratch)
        assert root.exists()
        from pathlib import Path
        assert Path(scratch).is_dir()
        return {"status":"done"}
    monkeypatch.setattr(isolation,"_run_isolated",execute)
    assert isolation.run_isolated("db","job","owner","export_geojson","p",{},Event())=={"status":"done"}
    from pathlib import Path
    assert observed and not Path(observed[0]).exists()
    assert root.is_dir()
