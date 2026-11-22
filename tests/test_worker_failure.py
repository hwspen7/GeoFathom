"""Real spawned-worker crash and cancellation: scratch directories must vanish."""
import os
from pathlib import Path
from threading import Event,Timer
import time
import pytest
from jobs import isolation,queue,leases
from storage.database import create_project,_connect,database_path

def crash(send,path,uid,owner,kind,project,payload,scratch):
    (Path(scratch)/"incomplete.bin").write_bytes(b"x")
    os._exit(73)

def hang(send,path,uid,owner,kind,project,payload,scratch):
    (Path(scratch)/"incomplete.bin").write_bytes(b"x")
    while True:
        time.sleep(.1)

@pytest.fixture
def isolated_job(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"jobs.sqlite"))
    monkeypatch.setenv("GEOFATHOM_EXTERNAL_WORKER","1")
    root=tmp_path/"scratch"
    monkeypatch.setenv("GEOFATHOM_SNAPSHOT_DIR",str(root))
    project=create_project("fault")["id"]
    uid=queue.queue_job(project,"export_geojson",{})["id"]
    owner="fault-"+uid
    with _connect() as c:
        queue._schema(c)
        assert leases.claim(c,uid,owner)
    return str(database_path().resolve()),uid,owner,project,root

def test_native_child_crash_cleans_parent_owned_scratch(isolated_job,monkeypatch):
    db,uid,owner,project,root=isolated_job
    monkeypatch.setattr(isolation,"_child_entry",crash)
    with pytest.raises(RuntimeError,match="subprocess|IPC"):
        isolation.run_isolated(db,uid,owner,"export_geojson",project,{},Event())
    assert list(root.iterdir())==[]

def test_lost_lease_terminates_hung_child(isolated_job,monkeypatch):
    db,uid,owner,project,root=isolated_job
    monkeypatch.setattr(isolation,"_child_entry",hang)
    lost=Event()
    timer=Timer(.5,lost.set);timer.start()
    try:
        with pytest.raises(RuntimeError,match="lease lost"):
            isolation.run_isolated(db,uid,owner,"export_geojson",project,{},lost)
    finally:
        timer.cancel()
    assert list(root.iterdir())==[]


def oversized_frame(send,path,uid,owner,kind,project,payload,scratch):
    # The receiver rejects frames before allocating more than its IPC budget.
    send.send_bytes(b"x" * 5_000_101)


def test_large_ipc_message_is_rejected_and_child_reaped(isolated_job,monkeypatch):
    db,uid,owner,project,root=isolated_job
    monkeypatch.setattr(isolation,"_child_entry",oversized_frame)
    with pytest.raises(RuntimeError,match="IPC"):
        isolation.run_isolated(db,uid,owner,"export_geojson",project,{},Event())
    assert list(root.iterdir())==[]


def test_watchdog_remains_responsive_during_blocked_ipc_read():
    from types import SimpleNamespace
    import json
    entered,release=Event(),Event()
    def read(maxlength):
        entered.set()
        assert release.wait(5)
        return json.dumps({"status":"ok","result":{"late":True}}).encode()
    reader=isolation.ResultReader(SimpleNamespace(recv_bytes=read))
    try:
        assert entered.wait(2)
        assert not reader.ready.wait(.05)
        with pytest.raises(RuntimeError,match="not ready"):
            reader.get()
    finally:
        release.set()
        reader.thread.join(5)
    assert reader.ready.is_set()
    assert reader.get()=={"late":True}
