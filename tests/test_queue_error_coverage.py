"""Queued-job state transition, ownership, progress and rollback coverage."""
import sqlite3
import time
from threading import Event
from types import SimpleNamespace

import pytest

from jobs import leases,queue
from storage.database import _connect,create_project,StorageError


@pytest.fixture
def queued(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"queue-edges.sqlite"))
    monkeypatch.setenv("GEOFATHOM_EXTERNAL_WORKER","1")
    project=create_project("Queue edge cases")["id"]
    item=queue.queue_job(project,"export_geojson",{})
    return project,item["id"]


def test_job_progress_obeys_lease_and_cancellation_fence(queued):
    project,uid=queued
    with _connect() as connection:
        queue._schema(connection)
        assert leases.claim(connection,uid,"progress-owner") is not None
    state={"value":10,"checked":0,"committed":0}
    tokens=[queue._ACTIVE_JOB.set(uid),queue._ACTIVE_PROGRESS.set(state),
            queue._ACTIVE_OWNER.set("progress-owner")]
    try:
        queue._progress(.5)
        assert queue.get_job(project,uid)["progress"]==50
        state["checked"]=time.monotonic()
        state["committed"]=time.monotonic()
        queue._progress(.5)  # Throttled; repeated value does not write.
        assert queue.get_job(project,uid)["progress"]==50
        with _connect() as c:
            c.execute("UPDATE gis_jobs SET cancel_requested=1 WHERE id=?",(uid,))
        state["checked"]=0
        with pytest.raises(RuntimeError,match="cancelled"):
            queue._progress(.9)
        with _connect() as c:
            c.execute("UPDATE gis_jobs SET cancel_requested=0,lease_expires=0 WHERE id=?",(uid,))
        with pytest.raises(RuntimeError,match="lease expired"):
            queue._progress(.9)
    finally:
        queue._ACTIVE_OWNER.reset(tokens[2])
        queue._ACTIVE_PROGRESS.reset(tokens[1])
        queue._ACTIVE_JOB.reset(tokens[0])


def test_progress_context_absence_is_a_safe_noop():
    token=queue._ACTIVE_JOB.set(None)
    try:assert queue._progress(1) is None
    finally:queue._ACTIVE_JOB.reset(token)
    token=queue._ACTIVE_JOB.set("not-running")
    state=queue._ACTIVE_PROGRESS.set(None)
    try:assert queue._progress(.4) is None
    finally:
        queue._ACTIVE_PROGRESS.reset(state)
        queue._ACTIVE_JOB.reset(token)


def test_progress_connection_rolls_back_unsafe_partial_sql(queued):
    _,uid=queued
    with pytest.raises(sqlite3.OperationalError):
        with queue._job_db() as connection:
            connection.execute("UPDATE gis_jobs SET progress=32 WHERE id=?",(uid,))
            connection.execute("SELECT FROM not_valid")
    with queue._job_db() as connection:
        assert connection.execute("SELECT progress FROM gis_jobs WHERE id=?",(uid,)).fetchone()[0]==0


def test_queue_validation_rejects_nonfinite_and_invalid_payloads(queued):
    project,_=queued
    with pytest.raises(StorageError,match="JSON object"):
        queue.queue_job(project,"export_geojson",[])
    with pytest.raises(ValueError):
        queue.queue_job(project,"export_geojson",{"bad":float("nan")})
    with pytest.raises(StorageError,match="Unsupported"):
        queue.queue_job(project,"made_up_job",{})
    with pytest.raises(StorageError,match="100 KB"):
        queue.queue_job(project,"export_geojson",{"padding":"x"*110000})


def test_lease_heartbeat_marks_lost_ownership_without_touching_other_owner(
    queued,monkeypatch,
):
    _,uid=queued
    # A one-cycle watchdog checks the real SQLite schema and returns on lost
    # ownership without attempting to continue a retired process.
    stop=SimpleNamespace(wait=lambda _:False)
    lost=Event()
    with _connect() as c:
        queue._schema(c)
    from storage.database import database_path
    queue._lease_heartbeat(uid,str(database_path()),"stale-owner",stop,lost)
    assert lost.is_set()


def test_lease_heartbeat_retries_transient_busy_database(monkeypatch):
    cycle=iter([False,True])
    stop=SimpleNamespace(wait=lambda _:next(cycle))
    errors=[]
    def inaccessible(*args,**kwargs):
        errors.append("busy")
        raise sqlite3.OperationalError("database is busy")
    monkeypatch.setattr(queue.sqlite3,"connect",inaccessible)
    queue._lease_heartbeat("task","missing.sqlite","owner",stop,Event())
    assert errors==["busy"]


def test_impl_refuses_unlisted_kind(queued):
    project,_=queued
    with pytest.raises(StorageError,match="Unsupported"):
        queue._execute_impl("unlisted",project,{})


def test_impl_postgis_sync_is_passed_correct_project_and_budget(queued,monkeypatch):
    project,_=queued
    from storage import postgis
    received=[]
    monkeypatch.setattr(postgis,"sync_project",
        lambda project_id,max_features:received.append((project_id,max_features)) or {"count":3})
    assert queue._execute_impl("postgis_sync",project,{"max_features":44})=={"count":3}
    assert received==[(project,44)]


def test_impl_rebuild_index_produces_real_sqlite_result(queued):
    project,_=queued
    result=queue._execute_impl("rebuild_index",project,{})
    assert result["engine"]=="SQLite R-tree"
    assert result["indexed_features"]==0
