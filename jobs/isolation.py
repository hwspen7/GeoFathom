"""Killable out-of-process raster analysis with CPU RSS and wall-time budgets.

Windows and Linux use multiprocessing spawn, isolating native GDAL/ONNX
allocations from FastAPI. Results traverse a one-way IPC pipe; the parent's
SQLite lease remains authoritative. GPU VRAM is monitored separately.
"""
import multiprocessing
import os
import time

from storage.database import StorageError


def _limit(name,default,minimum,maximum):
    try:
        value=int(os.getenv(name,str(default)))
    except ValueError as error:
        raise StorageError(f"{name} must be an integer.") from error
    if not minimum<=value<=maximum:
        raise StorageError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _child_entry(send,path,uid,owner,kind,project_id,payload):
    # Explicitly set the database context in the spawned interpreter.
    from storage.database import job_database_override
    from jobs import queue
    import time as clock
    token=job_database_override.set(path)
    active=queue._ACTIVE_JOB.set(uid)
    lease=queue._ACTIVE_OWNER.set(owner)
    state=queue._ACTIVE_PROGRESS.set({
        "value":10,"checked":clock.monotonic(),"committed":clock.monotonic()})
    try:
        outcome=queue._execute(kind,project_id,payload)
        send.send(("ok",outcome))
    except Exception as error:
        send.send(("error",str(error)[:250]))
    finally:
        queue._ACTIVE_PROGRESS.reset(state)
        queue._ACTIVE_OWNER.reset(lease)
        queue._ACTIVE_JOB.reset(active)
        job_database_override.reset(token)
        send.close()


def _terminate(process):
    if process.is_alive():
        process.terminate()
        process.join(timeout=3)
    if process.is_alive():
        process.kill()
        process.join(timeout=3)


def run_isolated(path,uid,owner,kind,project_id,payload,lost):
    """Execute a raster task in a monitored child process; return its result."""
    try:
        import psutil
    except ImportError as error:
        raise StorageError("Install psutil to enforce the raster RSS budget.") from error
    timeout=_limit("GEOFATHOM_RASTER_TIMEOUT_SECONDS",900,30,7200)
    rss_mb=_limit("GEOFATHOM_RASTER_RSS_MB",2048,256,16384)
    context=multiprocessing.get_context("spawn")
    receive,send=context.Pipe(duplex=False)
    process=context.Process(
        target=_child_entry,
        args=(send,path,uid,owner,kind,project_id,payload),
        daemon=False)
    started=time.monotonic()
    process.start()
    send.close()
    try:
        monitor=psutil.Process(process.pid)
        while True:
            if lost.is_set():
                raise RuntimeError("Worker lease lost during raster processing.")
            if time.monotonic()-started > timeout:
                raise RuntimeError("Raster processing exceeded the wall-time budget.")
            if receive.poll(.15):
                tag,result=receive.recv()
                if tag=="error":
                    raise RuntimeError(result)
                return result
            if not process.is_alive():
                # Check for a late IPC write, then report any native crash.
                if receive.poll(.05):
                    tag,result=receive.recv()
                    if tag=="ok":
                        return result
                    raise RuntimeError(result)
                raise RuntimeError(f"Raster subprocess exited without a result ({process.exitcode}).")
            try:
                if monitor.memory_info().rss > rss_mb*1024*1024:
                    raise RuntimeError("Raster subprocess exceeded its CPU RSS budget.")
            except psutil.NoSuchProcess:
                continue
            # A cancel flag cannot interrupt native GDAL/ONNX calls inside
            # Python: terminate the isolated child as soon as it is observed.
            from sqlite3 import connect
            connection=connect(path,timeout=5)
            try:
                row=connection.execute("""SELECT cancel_requested FROM gis_jobs
                    WHERE id=? AND lease_owner=? AND status='running'""",
                    (uid,owner)).fetchone()
                if row is None or row[0]:
                    raise RuntimeError("Raster task was cancelled.")
            finally:
                connection.close()
    finally:
        _terminate(process)
        receive.close()
