"""Persistent bounded background geospatial jobs with cooperative cancellation.

Uses SQLite WAL for status persistence and a small thread executor for local
deployments. Queued jobs are recovered lazily after restart; running jobs
interrupted by a process crash are marked interrupted (not silently marked
successful). Read-only analytics preserve project data on failure.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from threading import Lock
from uuid import uuid4
import json
import os

from storage.database import StorageError,_connect,_required_project,_now

KINDS={"topology_qa","spatial_select","export_geojson","postgis_sync","rebuild_index"}
_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix="geofathom-gis")
_LOCK=Lock()
_INITIALIZED=set()


def _schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS gis_jobs(
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL,
        progress INTEGER NOT NULL,
        result TEXT,
        error TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    c.execute("""CREATE INDEX IF NOT EXISTS gis_jobs_project
                 ON gis_jobs(project_id,created_at)""")


def _from_row(row):
    item=dict(row)
    item["payload"]=json.loads(item["payload"])
    if item["result"] is not None:item["result"]=json.loads(item["result"])
    item["cancel_requested"]=bool(item["cancel_requested"])
    return item


def _ensure():
    from storage.database import database_path
    path=str(database_path().resolve())
    with _LOCK:
        if path in _INITIALIZED:return
        with _connect() as c:
            _schema(c)
            c.execute("""UPDATE gis_jobs SET status='interrupted',
                error='Previous worker stopped before committing a result.',
                updated_at=? WHERE status='running'""",(_now(),))
            pending=[r["id"] for r in c.execute(
                "SELECT id FROM gis_jobs WHERE status='queued' ORDER BY created_at",
            ).fetchall()]
        _INITIALIZED.add(path)
        for uid in pending:_POOL.submit(_worker,uid,path)


def queue_job(project_id,kind,payload):
    _ensure()
    if kind not in KINDS:raise StorageError("Unsupported background GIS operation.")
    if not isinstance(payload,dict):raise StorageError("Job payload must be a JSON object.")
    serialized=json.dumps(payload,allow_nan=False)
    if len(serialized.encode("utf-8"))>100_000:
        raise StorageError("Job request exceeds 100 KB.")
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        active=c.execute("""SELECT count(*) FROM gis_jobs
           WHERE status IN ('queued','running')""").fetchone()[0]
        if active>=32:raise StorageError("Local background job queue is full.")
        uid=str(uuid4())
        now=_now()
        c.execute("""INSERT INTO gis_jobs(id,project_id,kind,payload,status,
            progress,cancel_requested,created_at,updated_at)
            VALUES(?,?,?,?,'queued',0,0,?,?)""",
            (uid,project_id,kind,serialized,now,now))
    _POOL.submit(_worker,uid,str(__import__("storage.database",fromlist=["database_path"])
                     .database_path().resolve()))
    return get_job(project_id,uid)


def get_job(project_id,job_id):
    _ensure()
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        row=c.execute("SELECT * FROM gis_jobs WHERE id=? AND project_id=?",
                      (job_id,project_id)).fetchone()
        if row is None:raise StorageError("Job not found.")
        return _from_row(row)


def list_jobs(project_id,limit=30):
    _ensure()
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        rows=c.execute("""SELECT * FROM gis_jobs WHERE project_id=?
                   ORDER BY created_at DESC,id DESC LIMIT ?""",
                   (project_id,limit)).fetchall()
    return [_from_row(r) for r in rows]


def cancel_job(project_id,job_id):
    _ensure()
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        row=c.execute("SELECT * FROM gis_jobs WHERE project_id=? AND id=?",
                      (project_id,job_id)).fetchone()
        if row is None:raise StorageError("Job not found.")
        if row["status"] in ("queued","running"):
            c.execute("""UPDATE gis_jobs
                SET cancel_requested=1,
                status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                updated_at=? WHERE id=?""",(_now(),job_id))
    return get_job(project_id,job_id)


def _execute(kind,project_id,payload):
    if kind=="topology_qa":
        from analysis.topology_qa import review_topology
        return review_topology(project_id,
            payload.get("layer_ids"),payload.get("study_area"),
            payload.get("minimum_area_m2",.01),
            payload.get("check_dangles",True),payload.get("max_issues",500))
    if kind=="spatial_select":
        from analysis.selection import select_features
        return select_features(project_id,payload["geometry"],
            payload.get("relation","intersects"),payload.get("layer_ids"),
            payload.get("limit",500),payload.get("offset",0),
            payload.get("visible_only",True))
    if kind=="export_geojson":
        from storage.database import export_project
        return export_project(project_id)
    if kind=="postgis_sync":
        from storage.postgis import sync_project
        return sync_project(project_id,payload.get("max_features",100000))
    if kind=="rebuild_index":
        from storage.paging import prepare_rtree
        with _connect() as c:
            c.execute("DELETE FROM feature_bounds")
            prepare_rtree(c)
            count=c.execute("SELECT count(*) FROM feature_bounds").fetchone()[0]
            return {"indexed_features":count,"engine":"SQLite R-tree"}
    raise StorageError("Unsupported GIS job.")


def _worker(uid,path):
    # The database path is captured at submission time so concurrent test
    # projects and reconfigured local users do not affect earlier tasks.
    from storage.database import job_database_override
    token=job_database_override.set(path)
    try:
        with _connect() as c:
            _schema(c)
            row=c.execute("SELECT * FROM gis_jobs WHERE id=?",(uid,)).fetchone()
            if row is None or row["status"]!="queued":return
            if row["cancel_requested"]:
                c.execute("UPDATE gis_jobs SET status='cancelled',updated_at=? WHERE id=?",
                          (_now(),uid));return
            c.execute("UPDATE gis_jobs SET status='running',progress=10,updated_at=? WHERE id=?",
                      (_now(),uid))
            project_id=row["project_id"];kind=row["kind"];payload=json.loads(row["payload"])
        try:
            outcome=_execute(kind,project_id,payload)
            result=json.dumps(outcome,allow_nan=False)
            if len(result.encode("utf-8"))>5_000_000:
                raise StorageError("GIS job output exceeded 5 MB; narrow the query.")
            with _connect() as c:
                row=c.execute("SELECT cancel_requested FROM gis_jobs WHERE id=?",(uid,)).fetchone()
                if row is None:return
                if row["cancel_requested"]:
                    c.execute("UPDATE gis_jobs SET status='cancelled',progress=100,"
                              "updated_at=? WHERE id=?",(_now(),uid))
                else:
                    c.execute("""UPDATE gis_jobs SET status='completed',
                        progress=100,result=?,updated_at=? WHERE id=?""",
                        (result,_now(),uid))
        except Exception as error:
            with _connect() as c:
                c.execute("""UPDATE gis_jobs SET status='failed',progress=100,
                    error=?,updated_at=? WHERE id=?""",
                    (str(error)[:250],_now(),uid))
    finally:
        job_database_override.reset(token)
