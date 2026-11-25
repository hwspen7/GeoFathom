"""Optional isolated terrain jobs with OS-enforced memory ceilings.

Only server-selected Python functions and local trusted arguments are passed
to the spawned worker. The temporary result channel is private to the job.
No hard-limit request silently falls back to an unbounded process.
"""
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import sys
import tempfile
from uuid import uuid4

from imagery.raster import RasterError
from geometry.measure import GeometryError
from .cancellation import TerrainCancelled,checkpoint
from . import compute_resources as cr


def hard_memory_available():
    if os.name=="nt":return True
    if not sys.platform.startswith("linux"):return False
    configured=os.getenv("GEOFATHOM_WORKER_CGROUP")
    if not configured:return False
    try:
        group=Path(configured).resolve(strict=True)
        return Path("/sys/fs/cgroup").resolve() in group.parents and (group/"memory.max").read_text().strip()!="max" and os.access(group/"cgroup.procs",os.W_OK)
    except OSError:return False


def _child(fn,args,limits,cancel,destination,hard):
    token=cr._active.set(limits)
    try:
        if hard:
            from jobs.hard_limits import _linux_join,_windows_join
            try:
                if os.name=="nt":
                    cap=_windows_join(limits.memory_bytes,"terrain-"+uuid4().hex)
                elif sys.platform.startswith("linux"):
                    cap=_linux_join(limits.memory_bytes)
                else:raise RuntimeError("Hard terrain memory protection is not supported on this OS.")
                if not 0<cap<=limits.memory_bytes:raise RuntimeError("Invalid OS memory boundary.")
            except Exception as error:
                raise cr.ResourceBusy("OS memory protection could not be established: "+str(error)) from error
        checkpoint(cancel)
        value=fn(*args,cancel=cancel)
        checkpoint(cancel)
        packet=("ok",value)
    except (RasterError,GeometryError,ValueError,TerrainCancelled,cr.ResourceBusy) as error:
        packet=(type(error).__name__,str(error))
    except MemoryError:
        packet=("ResourceBusy","Terrain worker exceeded its available memory.")
    except Exception as error:
        packet=("RuntimeError",str(error))
    finally:
        cr._active.reset(token)
    with open(destination,"wb") as stream:
        pickle.dump(packet,stream,protocol=pickle.HIGHEST_PROTOCOL)


def isolated_call(fn,args,limits,cancel,hard=True):
    if hard and not hard_memory_available():
        raise cr.ResourceBusy("Hard memory mode requires a Windows Job Object or a delegated Linux cgroup v2.")
    ctx=mp.get_context("spawn")
    event=ctx.Event()
    with tempfile.TemporaryDirectory(prefix="geofathom-terrain-worker-") as directory:
        path=Path(directory)/"result"
        worker=ctx.Process(target=_child,args=(fn,args,limits,event,path,hard))
        worker.start()
        try:
            while worker.is_alive():
                try:checkpoint(cancel)
                except (TerrainCancelled,cr.ResourceBusy):
                    event.set()
                    worker.join(timeout=3)
                    if worker.is_alive():worker.terminate()
                    raise
                worker.join(timeout=.1)
            if worker.exitcode!=0 or not path.exists():
                raise cr.ResourceBusy("Isolated terrain worker stopped without a result; inspect the memory budget.")
            with path.open("rb") as stream:
                kind,value=pickle.load(stream)
            if kind=="ok":return value
            errors={"RasterError":RasterError,"GeometryError":GeometryError,"ValueError":ValueError,
                    "TerrainCancelled":TerrainCancelled,"ResourceBusy":cr.ResourceBusy,"RuntimeError":RuntimeError}
            raise errors.get(kind,RuntimeError)(value)
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=3)
                if worker.is_alive():worker.kill()
            worker.join()
            worker.close()
