"""Persistent bounded background geospatial jobs with cooperative cancellation.

Uses SQLite WAL for status persistence and a small thread executor for local
deployments. Queued jobs are recovered lazily after restart; running jobs
interrupted by a process crash are marked interrupted (not silently marked
successful). Read-only analytics preserve project data on failure.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextlib import contextmanager
from threading import BoundedSemaphore
import sqlite3
import time
from datetime import datetime,timezone
from threading import Lock,Thread,Event
from uuid import UUID,uuid4
import json
import os

from storage.database import (StorageError,_connect,_required_project,
                              _now,database_path)
from .leases import (PROCESS_ID,LEASE_SECONDS,ensure_lease_schema,
    recover_expired,claim,heartbeat,is_owner,release_slot)

KINDS={"vector_import","vector_export","topology_qa","spatial_select","export_geojson","postgis_sync",
       "rebuild_index","spectral_index","spectral_change","semantic_segmentation",
       "stac_ndvi","remote_windowed"}
_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix="geofathom-gis")
_LOCK=Lock()
_INITIALIZED=set()
_ACTIVE_JOB=ContextVar("geofathom_current_gis_job", default=None)
_ACTIVE_PROGRESS=ContextVar("geofathom_progress_throttle", default=None)
_ACTIVE_OWNER=ContextVar("geofathom_lease_owner",default=None)
# Limit simultaneous full-size raster tasks even when the general queue has
# multiple worker threads. This gate is per process, not a distributed quota.
_RASTER_GATE=BoundedSemaphore(1)


@contextmanager
def _job_db():
    """Lightweight progress connection without repeated schema/rtree setup."""
    c=sqlite3.connect(database_path(), timeout=5)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _progress(fraction):
    """Throttle SQLite updates while polling for cooperative cancellation."""
    uid=_ACTIVE_JOB.get()
    if uid is None:
        return
    state=_ACTIVE_PROGRESS.get()
    if state is None:
        return
    if _cancel_marker(uid).exists():raise RuntimeError("GIS operation cancelled.")
    completed=max(10,min(95,10+int(80*float(fraction))))
    now=time.monotonic()
    # Check cancellation every 0.2 seconds or every 5% progression, rather
    # than opening a database connection on every input tile.
    if completed-state["value"] < 5 and now-state["checked"] < .2:
        return
    with _job_db() as c:
        row=c.execute("""SELECT progress,cancel_requested,lease_owner,
            lease_expires FROM gis_jobs WHERE id=?""",(uid,)).fetchone()
        owner=_ACTIVE_OWNER.get()
        if (row is None or row["cancel_requested"] or
                (owner is not None and
                 (row["lease_owner"]!=owner or
                  row["lease_expires"] is None or
                  row["lease_expires"]<time.time()))):
            raise RuntimeError("Running GIS operation was cancelled or its lease expired.")
        if (completed > row["progress"] and
                (completed-row["progress"] >= 5
                 or now-state["committed"] >= .5)):
            c.execute("UPDATE gis_jobs SET progress=?,updated_at=? WHERE id=?",
                      (completed,_now(),uid))
            state["value"]=completed
            state["committed"]=now
    state["checked"]=now



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
    c.execute("""CREATE TABLE IF NOT EXISTS gis_job_results(
        job_id TEXT PRIMARY KEY REFERENCES gis_jobs(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        size_bytes INTEGER NOT NULL
    )""")
    ensure_lease_schema(c)


def _from_row(row):
    item=dict(row)
    item["payload"]=json.loads(item["payload"])
    item["cancel_requested"]=bool(item["cancel_requested"])
    result=item.pop("resolved_result",item.get("result"))
    item["result"]=json.loads(result) if result is not None else None
    item["has_result"]=bool(item.get("has_result",result is not None))
    return item


def _ensure():
    from storage.database import database_path
    path=str(database_path().resolve())
    with _LOCK:
        if path in _INITIALIZED:return
        with _connect() as c:
            _schema(c)
            recover_expired(c)
            pending=[r["id"] for r in c.execute(
                "SELECT id FROM gis_jobs WHERE status='queued' ORDER BY created_at",
            ).fetchall()]
        _INITIALIZED.add(path)
        if os.getenv("GEOFATHOM_EXTERNAL_WORKER")!="1":
            for uid in pending:_POOL.submit(_worker,uid,path)


def queue_job(project_id,kind,payload):
    _ensure()
    if kind not in KINDS:raise StorageError("Unsupported background GIS operation.")
    if not isinstance(payload,dict):raise StorageError("Job payload must be a JSON object.")
    if kind=="stac_ndvi":
        payload={**payload,"full_resolution":True}
    if kind=="remote_windowed":
        from imagery.remote_managed import validate
        payload=validate(payload).model_dump(mode="json")
    serialized=json.dumps(payload,allow_nan=False)
    if len(serialized.encode("utf-8"))>100_000:
        raise StorageError("Job request exceeds 100 KB.")
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id);_schema(c)
        recover_expired(c)
        active=c.execute("""SELECT count(*) FROM gis_jobs
           WHERE status IN ('queued','running')""").fetchone()[0]
        if active>=32:raise StorageError("Local background job queue is full.")
        uid=str(uuid4())
        now=_now()
        c.execute("""INSERT INTO gis_jobs(id,project_id,kind,payload,status,
            progress,cancel_requested,created_at,updated_at)
            VALUES(?,?,?,?,'queued',0,0,?,?)""",
            (uid,project_id,kind,serialized,now,now))
    if os.getenv("GEOFATHOM_EXTERNAL_WORKER")!="1":
        _POOL.submit(_worker,uid,str(database_path().resolve()))
    return get_job(project_id,uid)


def get_job(project_id,job_id,include_result=True):
    _ensure()
    with _connect() as c:
        _required_project(c,project_id)
        if include_result:
            row=c.execute("""SELECT j.*,
                COALESCE(r.content,j.result) AS resolved_result,
                (r.job_id IS NOT NULL OR j.result IS NOT NULL) AS has_result
                FROM gis_jobs j LEFT JOIN gis_job_results r ON r.job_id=j.id
                WHERE j.id=? AND j.project_id=?""",
                (job_id,project_id)).fetchone()
        else:
            row=c.execute("""SELECT j.id,j.project_id,j.kind,j.payload,j.status,
                j.progress,NULL AS result,j.error,j.cancel_requested,
                j.created_at,j.updated_at,
                (r.job_id IS NOT NULL OR j.result IS NOT NULL) AS has_result
                FROM gis_jobs j LEFT JOIN gis_job_results r ON r.job_id=j.id
                WHERE j.id=? AND j.project_id=?""",
                (job_id,project_id)).fetchone()
        if row is None:raise StorageError("Job not found.")
        return _from_row(row)


def list_jobs(project_id,limit=30):
    """Return metadata only, never load stored GeoJSON into polling results."""
    _ensure()
    with _connect() as c:
        _required_project(c,project_id)
        rows=c.execute("""SELECT j.id,j.project_id,j.kind,j.payload,j.status,
                   j.progress,NULL AS result,j.error,j.cancel_requested,
                   j.created_at,j.updated_at,
                   (r.job_id IS NOT NULL OR j.result IS NOT NULL) AS has_result
                   FROM gis_jobs j LEFT JOIN gis_job_results r ON r.job_id=j.id
                   WHERE j.project_id=? ORDER BY j.created_at DESC,j.id DESC LIMIT ?""",
                   (project_id,limit)).fetchall()
    return [_from_row(r) for r in rows]


def _cancel_marker(job_id):
    if str(UUID(job_id))!=job_id:raise StorageError('Invalid job identifier.')
    directory=database_path().with_suffix(database_path().suffix+'.cancellations')
    return directory/job_id

def cancel_job(project_id,job_id):
    with _job_db() as c:
        initialized=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gis_jobs'").fetchone()
    if not initialized:_ensure()
    # A filesystem marker can reach the importing worker while its atomic SQL
    # transaction owns the write lock. It also works with external workers
    # sharing this local database; no half-import needs to be committed.
    with _job_db() as c:
        row=c.execute('SELECT * FROM gis_jobs WHERE project_id=? AND id=?',(project_id,job_id)).fetchone()
        if row is None:raise StorageError('Job not found.')
    marker=None
    if row['status'] in ('queued','running'):
        marker=_cancel_marker(job_id);marker.parent.mkdir(parents=True,exist_ok=True);marker.touch()
    _ensure()
    with _connect() as c:
        c.execute("""UPDATE gis_jobs SET cancel_requested=1,
            status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
            updated_at=? WHERE id=? AND project_id=? AND status IN ('queued','running')""",(_now(),job_id,project_id))
    if row['kind']=='vector_import' and row['status']=='queued':
        from storage.exchange import discard_stage
        discard_stage(project_id,json.loads(row['payload'])['upload_id'])
    result=get_job(project_id,job_id)
    if marker and result['status'] not in ('queued','running'):marker.unlink(missing_ok=True)
    return result


def _execute(kind,project_id,payload):
    if kind in {"spectral_index","spectral_change","semantic_segmentation"}:
        from storage.snapshots import analysis_snapshot
        with analysis_snapshot(kind,payload) as provenance:
            if os.getenv("GEOFATHOM_DISTRIBUTED_DSN"):
                from .distributed import dispatch
                outcome=dispatch(kind,payload,provenance,_progress)
                provenance["execution"]="postgresql-remote"
            else:
                if os.getenv("GEOFATHOM_VERSION_DIR"):
                    from storage.versions import archive_inputs
                    archive_inputs(os.environ["GEOFATHOM_VERSION_DIR"],provenance)
                    provenance["version_archive"]=True
                outcome=_execute_impl(kind,project_id,payload)
            provenance["analysis_engine"]=outcome.get("engine")
            if kind=="semantic_segmentation":
                provenance["model_id"]=payload["model_id"]
                provenance["model_sha256"]=provenance["model_files_sha256"][payload["model_id"]+".onnx"]
            outcome["provenance"]=provenance
            return outcome
    return _execute_impl(kind,project_id,payload)


def check_cancelled():
    uid=_ACTIVE_JOB.get()
    if uid is None:return
    if _cancel_marker(uid).exists():raise RuntimeError("GIS operation cancelled before commit.")
    with _job_db() as c:
        row=c.execute("SELECT cancel_requested,lease_owner FROM gis_jobs WHERE id=?",(uid,)).fetchone()
        if row is None or row["cancel_requested"] or row["lease_owner"]!=_ACTIVE_OWNER.get():
            raise RuntimeError("GIS operation cancelled before commit.")

def _execute_impl(kind,project_id,payload):
    if kind=="vector_import":
        from storage.exchange import execute_import
        return execute_import(project_id,payload,_progress,check_cancelled)
    if kind=="vector_export":
        from storage.exchange import execute_export
        return execute_export(project_id,payload,_progress,check_cancelled)
    if kind=="remote_windowed":
        from imagery.remote_managed import run_managed
        return run_managed(payload,_ACTIVE_JOB.get(),_progress,check_cancelled)
    if kind=="stac_ndvi":
        from imagery.remote import run_stac_ndvi
        return run_stac_ndvi(payload["collection"],payload["item_id"],
            payload.get("threshold",.25),payload.get("max_side",4096),
            payload.get("tile_size",256),
            payload.get("max_pixels",16_777_216),
            payload.get("memory_mb",32),progress=_progress,
            provider=payload.get("provider","earth-search"))
    if kind in {"spectral_index","spectral_change","semantic_segmentation"}:
        from imagery.store import image_file
        from vision.geoai import spectral_index, spectral_change
        from vision.semantic import semantic_segmentation
        image_id=payload["image_id"]
        path=image_file(image_id)
        if type(payload.get("full_resolution",False)) is not bool:
            raise StorageError("full_resolution must be a boolean.")
        if payload.get("full_resolution",False):
            from vision.tiled import (spectral_index_tiled,
                                     spectral_change_tiled,
                                     semantic_segmentation_tiled)
            options={
                "tile_size":payload.get("tile_size",256),
                "max_pixels":payload.get("max_pixels",16_777_216),
                "memory_mb":payload.get("memory_mb",32),
                "progress":_progress,
            }
            if kind=="semantic_segmentation":
                return semantic_segmentation_tiled(
                    path,image_id,payload["model_id"],
                    payload.get("minimum_confidence",.55),
                    max_pixels=options["max_pixels"],
                    memory_mb=options["memory_mb"],
                    progress=_progress)
            if kind=="spectral_index":
                return spectral_index_tiled(
                    path,image_id,payload.get("index","ndvi"),
                    payload["first_band"],payload["second_band"],
                    payload.get("threshold",.2),**options)
            other_id=payload["after_image_id"]
            return spectral_change_tiled(
                path,image_file(other_id),image_id,other_id,
                payload["first_band"],payload["second_band"],
                payload.get("threshold",.2),**options)
        if kind=="spectral_index":
            return spectral_index(
                path,image_id,payload.get("index","ndvi"),
                payload["first_band"],payload["second_band"],
                payload.get("threshold",.2),payload.get("max_side",512))
        if kind=="semantic_segmentation":
            return semantic_segmentation(
                path,image_id,payload["model_id"],
                payload.get("minimum_confidence",.55),
                payload.get("max_side",512))
        other_id=payload["after_image_id"]
        return spectral_change(
            path,image_file(other_id),image_id,other_id,
            payload["first_band"],payload["second_band"],
            payload.get("threshold",.2),payload.get("max_side",512))
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


def _lease_heartbeat(uid,path,owner,stop,lost):
    """Renew the shared lease during blocking GDAL/ONNX operations."""
    while not stop.wait(3.):
        try:
            c=sqlite3.connect(path,timeout=5)
            c.row_factory=sqlite3.Row
            try:
                if not heartbeat(c,uid,owner):
                    lost.set()
                    return
                c.commit()
            finally:
                c.close()
        except sqlite3.Error:
            # A transient busy database does not immediately invalidate an
            # existing lease. Subsequent attempts may renew it before expiry.
            continue


def _worker(uid,path):
    from storage.database import job_database_override
    token=job_database_override.set(path)
    owner=PROCESS_ID+":"+uid+":"+str(uuid4())
    acquired=False
    stop=Event()
    lost=Event()
    thread=None
    try:
        # A claimed raster slot may be busy in another process. Keep the
        # queued task pending instead of exceeding the global resource limit.
        deadline=time.monotonic()+120
        while True:
            with _connect() as c:
                c.execute("BEGIN IMMEDIATE")
                _schema(c)
                recover_expired(c)
                row=claim(c,uid,owner)
                if row is None:
                    status=c.execute("SELECT status FROM gis_jobs WHERE id=?",
                                     (uid,)).fetchone()
                    pending=bool(status and status["status"]=="queued")
                else:
                    pending=False
            if row is not None:
                acquired=True
                break
            if not pending:
                return
            if time.monotonic()>=deadline:
                # The external scheduler polls queued rows; the embedded
                # executor must explicitly resubmit an unclaimed job.
                if os.getenv("GEOFATHOM_EXTERNAL_WORKER")!="1":
                    _POOL.submit(_worker,uid,path)
                return
            time.sleep(.2)
        project_id=row["project_id"]
        kind=row["kind"]
        payload=json.loads(row["payload"])
        thread=Thread(target=_lease_heartbeat,
                      args=(uid,path,owner,stop,lost),daemon=True)
        thread.start()
        try:
            active_token=_ACTIVE_JOB.set(uid)
            progress_token=_ACTIVE_PROGRESS.set({
                "value":10,"checked":time.monotonic(),
                "committed":time.monotonic()})
            owner_token=_ACTIVE_OWNER.set(owner)
            try:
                if (kind in {"spectral_index","spectral_change",
                             "semantic_segmentation","stac_ndvi","remote_windowed"}
                        and (((payload.get("full_resolution") is True or kind=="remote_windowed")
                             and os.getenv("GEOFATHOM_RASTER_ISOLATE","1")=="1")
                             or os.getenv("GEOFATHOM_WORKER_MEMORY_MB","0")!="0")):
                    from .isolation import run_isolated
                    outcome=run_isolated(path,uid,owner,kind,project_id,payload,lost)
                else:
                    outcome=_execute(kind,project_id,payload)
            finally:
                _ACTIVE_OWNER.reset(owner_token)
                _ACTIVE_PROGRESS.reset(progress_token)
                _ACTIVE_JOB.reset(active_token)
            result=json.dumps(outcome,allow_nan=False)
            result_bytes=len(result.encode("utf-8"))
            if result_bytes>5_000_000:
                raise StorageError("GIS job output exceeded 5 MB; narrow the query.")
            if lost.is_set():
                return
            with _connect() as c:
                c.execute("BEGIN IMMEDIATE")
                if not is_owner(c,uid,owner):
                    return
                row=c.execute("SELECT cancel_requested FROM gis_jobs WHERE id=?",
                              (uid,)).fetchone()
                if row is None:return
                if (row["cancel_requested"] or _cancel_marker(uid).exists()) and not (kind=="vector_import" and outcome.get("committed")):
                    c.execute("""UPDATE gis_jobs SET status='cancelled',progress=100,
                        lease_owner=NULL,lease_expires=NULL,updated_at=?
                        WHERE id=? AND lease_owner=?""",(_now(),uid,owner))
                else:
                    c.execute("""INSERT INTO gis_job_results(job_id,content,size_bytes)
                        VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET
                        content=excluded.content,size_bytes=excluded.size_bytes""",
                        (uid,result,result_bytes))
                    c.execute("""UPDATE gis_jobs SET status='completed',
                        progress=100,result=NULL,lease_owner=NULL,lease_expires=NULL,
                        updated_at=? WHERE id=? AND lease_owner=?""",
                        (_now(),uid,owner))
                release_slot(c,owner)
        except Exception as error:
            with _connect() as c:
                c.execute("BEGIN IMMEDIATE")
                if not is_owner(c,uid,owner):
                    return
                row=c.execute("SELECT cancel_requested FROM gis_jobs WHERE id=?",
                              (uid,)).fetchone()
                if row is None:return
                if row["cancel_requested"] or _cancel_marker(uid).exists():
                    c.execute("""UPDATE gis_jobs SET status='cancelled',
                        progress=100,error=NULL,result=NULL,lease_owner=NULL,
                        lease_expires=NULL,updated_at=? WHERE id=? AND lease_owner=?""",
                        (_now(),uid,owner))
                else:
                    c.execute("""UPDATE gis_jobs SET status='failed',progress=100,
                        error=?,lease_owner=NULL,lease_expires=NULL,updated_at=?
                        WHERE id=? AND lease_owner=?""",
                        (str(error)[:250],_now(),uid,owner))
                release_slot(c,owner)
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=5)
        try:
            if acquired:
                # Never release a successor's slot. A stale owner releases only
                # a row that still carries its exact unique token.
                with _connect() as c:
                    release_slot(c,owner)
                    row=c.execute('SELECT kind,status FROM gis_jobs WHERE id=?',(uid,)).fetchone()
                    if row and row['kind']=='remote_windowed' and row['status']!='completed':
                        from imagery.remote_managed import result_path
                        result_path(uid).unlink(missing_ok=True)
        finally:
            # Even a database failure during slot cleanup must not poison the
            # next job's ContextVar on this executor thread.
            job_database_override.reset(token)
