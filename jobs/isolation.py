"""Killable out-of-process raster analysis with CPU RSS and wall-time budgets.

Windows and Linux use multiprocessing spawn, isolating native GDAL/ONNX
allocations from FastAPI. Results traverse a one-way IPC pipe; the parent's
SQLite lease remains authoritative. GPU VRAM is monitored separately.
"""
import multiprocessing
import os
import time
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from threading import Event, Thread

from storage.database import StorageError


def _limit(name,default,minimum,maximum):
    try:
        value=int(os.getenv(name,str(default)))
    except ValueError as error:
        raise StorageError(f"{name} must be an integer.") from error
    if not minimum<=value<=maximum:
        raise StorageError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _child_entry(send,path,uid,owner,kind,project_id,payload,scratch):
    # The parent owns the directory, including after forced termination.
    os.environ['GEOFATHOM_SNAPSHOT_DIR']=scratch
    os.environ['GEOFATHOM_RASTER_TEMP_DIR']=scratch
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
        from .hard_limits import enforce
        enforce(str(Path(path).resolve()))
        from .resources import configure_child
        from sqlite3 import connect
        with __import__("contextlib").closing(connect(path,timeout=5)) as db:
            row=db.execute("""SELECT name FROM gis_job_slots WHERE owner=?
                AND name LIKE 'compute:%'""",(owner,)).fetchone()
        configure_child(int(row[0].split(":")[1]) if row else 0)
        outcome=queue._execute(kind,project_id,payload)
        # Use bounded JSON IPC rather than unbounded pickled application results.
        data=json.dumps({"status":"ok","result":outcome},allow_nan=False).encode("utf-8")
        if len(data)>5_000_100:
            raise StorageError("GIS job output exceeded 5 MB; narrow the query.")
        send.send_bytes(data)
    except Exception as error:
        send.send_bytes(json.dumps({"status":"error","error":str(error)[:250]}).encode("utf-8"))
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


def _read_result(receive):
    try:
        message=json.loads(receive.recv_bytes(maxlength=5_000_100))
    except (EOFError,OSError,ValueError) as error:
        raise RuntimeError("Raster subprocess IPC closed or returned invalid data.") from error
    # A crashed or corrupted child must never masquerade as a valid result.
    if not isinstance(message, dict):
        raise RuntimeError("Raster subprocess IPC returned an invalid envelope.")
    if message.get("status") == "error" and isinstance(message.get("error"), str):
        raise RuntimeError(message["error"])
    if message.get("status") != "ok" or "result" not in message:
        raise RuntimeError("Raster subprocess IPC returned an invalid envelope.")
    return message["result"]


class ResultReader:
    """Drain one bounded IPC frame off the watchdog thread.

    A readable pipe may contain only the first bytes of a large message.
    The parent must remain able to enforce cancellation and wall-time budgets
    even when a failed child stops halfway through that message.
    """
    def __init__(self, receive):
        self.ready = Event()
        self.result = None
        self.error = None
        self.thread = Thread(target=self._read, args=(receive,),
                             name="geofathom-ipc-reader", daemon=True)
        self.thread.start()

    def _read(self, receive):
        try:
            self.result = _read_result(receive)
        except Exception as error:
            self.error = error
        finally:
            self.ready.set()

    def get(self):
        if not self.ready.is_set():
            raise RuntimeError("Raster subprocess IPC result is not ready.")
        if self.error is not None:
            raise self.error
        return self.result


def cleanup_child(process, receive, send, reader):
    """Close both parent endpoints and reap the child after any outcome."""
    try:
        if process.pid is not None:
            _terminate(process)
            process.join(timeout=3)
            if process.is_alive():
                raise RuntimeError("Raster subprocess could not be terminated.")
        process.close()
    finally:
        send.close()
        # Closing the child's writer on termination wakes the background read.
        # Join it before closing the receiving handle to avoid a handle race.
        if reader is not None:
            reader.thread.join(timeout=3)
        receive.close()


def run_isolated(path,uid,owner,kind,project_id,payload,lost):
    root=os.getenv("GEOFATHOM_SNAPSHOT_DIR") or os.getenv("GEOFATHOM_RASTER_TEMP_DIR")
    if root:
        Path(root).mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix="geofathom-worker-",dir=root) as scratch:
        return _run_isolated(path,uid,owner,kind,project_id,payload,lost,scratch)


def _run_isolated(path,uid,owner,kind,project_id,payload,lost,scratch):
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
        args=(send,path,uid,owner,kind,project_id,payload,scratch),
        daemon=False)
    started=time.monotonic()
    reader=None
    try:
        process.start()
        send.close()
        reader=ResultReader(receive)
        try:
            monitor=psutil.Process(process.pid)
        except psutil.NoSuchProcess as error:
            raise RuntimeError("Raster subprocess exited before monitoring.") from error
        while True:
            if lost.is_set():
                raise RuntimeError("Worker lease lost during raster processing.")
            if time.monotonic()-started > timeout:
                raise RuntimeError("Raster processing exceeded the wall-time budget.")
            if reader.ready.wait(.15):
                if lost.is_set():
                    raise RuntimeError("Worker lease lost during raster processing.")
                if time.monotonic()-started > timeout:
                    raise RuntimeError("Raster processing exceeded the wall-time budget.")
                return reader.get()
            if not process.is_alive():
                # Check for a late IPC write, then report any native crash.
                if reader.ready.wait(.15):
                    if lost.is_set():
                        raise RuntimeError("Worker lease lost during raster processing.")
                    return reader.get()
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
        cleanup_child(process,receive,send,reader)
