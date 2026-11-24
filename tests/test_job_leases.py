"""Cross-process SQLite lease, heartbeat, global-slot and recovery tests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event,Thread
import time

import pytest

from jobs import leases
from jobs import queue
from storage.database import _connect,create_project


@pytest.fixture(autouse=True)
def setup(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"leases.sqlite"))
    monkeypatch.setenv("GEOFATHOM_EXTERNAL_WORKER","1")


def _queued(project,kind="export_geojson",payload=None):
    return queue.queue_job(project,kind,payload or {})["id"]


def test_only_one_worker_can_claim_same_job_across_concurrent_connections():
    project=create_project("atomic")["id"]
    uid=_queued(project)
    def attempt(i):
        with _connect() as connection:
            queue._schema(connection)
            return leases.claim(connection,uid,"node-"+str(i))
    with ThreadPoolExecutor(max_workers=8) as workers:
        claims=list(workers.map(attempt,range(8)))
    assert sum(x is not None for x in claims)==1
    with _connect() as connection:
        row=connection.execute("""SELECT status,attempts,lease_owner
            FROM gis_jobs WHERE id=?""",(uid,)).fetchone()
        assert row["status"]=="running"
        assert row["attempts"]==1
        assert row["lease_owner"].startswith("node-")


def test_valid_lease_survives_another_process_recovery_and_expires_explicitly():
    project=create_project("recovery")["id"]
    uid=_queued(project)
    started=time.time()
    with _connect() as c:
        queue._schema(c)
        assert leases.claim(c,uid,"worker-A",now=started)
    with _connect() as c:
        leases.recover_expired(c,now=started+15)
        assert c.execute("SELECT status FROM gis_jobs WHERE id=?",
                         (uid,)).fetchone()[0]=="running"
        assert leases.heartbeat(c,uid,"worker-A",now=started+16)
    with _connect() as c:
        leases.recover_expired(c,now=started+18)
        assert c.execute("SELECT status FROM gis_jobs WHERE id=?",
                         (uid,)).fetchone()[0]=="running"
        leases.recover_expired(c,now=started+leases.LEASE_SECONDS+18)
        status=c.execute("SELECT status FROM gis_jobs WHERE id=?",
                         (uid,)).fetchone()[0]
    assert status=="interrupted"
    with _connect() as c:
        assert not leases.is_owner(c,uid,"worker-A")
        assert leases.claim(c,uid,"worker-B") is None


def test_global_raster_and_gpu_slots_are_cross_job_atomic():
    project=create_project("slots")["id"]
    a=_queued(project,"spectral_index",{"full_resolution":True})
    b=_queued(project,"spectral_index",{"full_resolution":True})
    c=_queued(project,"semantic_segmentation",{"full_resolution":False})
    d=_queued(project,"semantic_segmentation",{"full_resolution":False})
    with _connect() as db:
        queue._schema(db)
        assert leases.claim(db,a,"raster-node",now=time.time()) is not None
    with _connect() as db:
        assert leases.claim(db,b,"other-raster") is None
        assert leases.claim(db,c,"gpu-node") is not None
    with _connect() as db:
        assert leases.claim(db,d,"other-gpu") is None
        assert not leases.heartbeat(db,a,"attacker")
        leases.release_slot(db,"raster-node")
        leases.release_slot(db,"gpu-node")
    with _connect() as db:
        assert leases.claim(db,b,"other-raster") is not None
        assert leases.claim(db,d,"other-gpu") is not None


def test_completion_requires_current_lease_and_cannot_be_forged():
    project=create_project("ownership")["id"]
    uid=_queued(project)
    with _connect() as c:
        queue._schema(c)
        leases.claim(c,uid,"node-A")
    with _connect() as c:
        assert leases.is_owner(c,uid,"node-A")
        assert not leases.is_owner(c,uid,"node-B")
        c.execute("UPDATE gis_jobs SET lease_expires=0 WHERE id=?",(uid,))
    with _connect() as c:
        assert not leases.is_owner(c,uid,"node-A")
        leases.recover_expired(c)
        assert c.execute("SELECT status FROM gis_jobs WHERE id=?",
                         (uid,)).fetchone()[0]=="interrupted"


def test_terminal_job_retention_cascades_to_results():
    project=create_project("retention")["id"]
    uid=_queued(project)
    with _connect() as c:
        queue._schema(c)
        c.execute("""UPDATE gis_jobs SET status='completed',
            updated_at='2020-01-01T00:00:00+00:00' WHERE id=?""",(uid,))
        c.execute("""INSERT INTO gis_job_results(job_id,content,size_bytes)
            VALUES(?,?,?)""",(uid,"{}",2))
        assert leases.prune_old_jobs(c,days=30)==1
    with _connect() as c:
        assert c.execute("SELECT count(*) FROM gis_job_results").fetchone()[0]==0


def test_external_worker_process_loop_executes_queued_task():
    project=create_project("external")["id"]
    uid=_queued(project)
    done=Event()
    runner=Thread(target=lambda:queue._ensure(),daemon=True)
    runner.start();runner.join(2)
    from jobs.worker import run_worker
    worker=Thread(target=lambda:run_worker(poll=.05,stop=done,max_workers=2),
                  daemon=True)
    worker.start()
    try:
        until=time.monotonic()+8
        while time.monotonic()<until:
            item=queue.get_job(project,uid)
            if item["status"]=="completed":
                break
            time.sleep(.05)
        assert item["status"]=="completed",item
        assert item["result"]["type"]=="FeatureCollection"
    finally:
        done.set()
        worker.join(5)
