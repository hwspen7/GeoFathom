"""Test the global CPU-slot limit across independent OS processes."""
from multiprocessing import get_context
import time

from jobs import queue,leases
from storage.database import create_project,_connect

def acquire(db,uid,owner,start,results):
    # Spawned interpreters use the same database, not inherited Python locks.
    import sqlite3
    conn=sqlite3.connect(db,timeout=10)
    conn.row_factory=sqlite3.Row
    try:
        start.wait(10)
        eligible=leases.claim(conn,uid,owner)
        conn.commit()
        results.put(bool(eligible))
    finally:
        conn.close()

def test_global_concurrency_across_spawned_processes(tmp_path,monkeypatch):
    path=tmp_path/"admission.sqlite"
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(path))
    monkeypatch.setenv("GEOFATHOM_EXTERNAL_WORKER","1")
    monkeypatch.setenv("GEOFATHOM_COMPUTE_SLOTS","2")
    project=create_project("compute")["id"]
    ids=[queue.queue_job(project,"export_geojson",{})["id"] for _ in range(4)]
    ctx=get_context("spawn")
    gate=ctx.Event();answers=ctx.Queue()
    procs=[ctx.Process(target=acquire,args=(str(path),uid,str(i),gate,answers)) for i,uid in enumerate(ids)]
    try:
        for proc in procs:proc.start()
        gate.set()
        observed=[answers.get(timeout=20) for _ in ids]
        assert sum(observed)==2
        for proc in procs:
            proc.join(10)
            assert proc.exitcode==0
        with _connect() as conn:
            assert conn.execute("SELECT count(*) FROM gis_jobs WHERE status='running'").fetchone()[0]==2
            assert conn.execute("SELECT count(*) FROM gis_job_slots WHERE name LIKE 'compute:%' AND owner IS NOT NULL").fetchone()[0]==2
            leases.recover_expired(conn,time.time()+leases.LEASE_SECONDS+1)
            assert conn.execute("SELECT count(*) FROM gis_job_slots WHERE owner IS NOT NULL").fetchone()[0]==0
    finally:
        for proc in procs:
            if proc.is_alive():proc.terminate()
            if proc.pid is not None:proc.join(5)
