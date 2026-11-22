"""Opt-in PostgreSQL broker for pure local-image raster analysis.

API project transactions remain authoritative in local SQLite. A remote
compute node requires PostgreSQL and the shared content-addressed archive,
not access to the API database. Expired leases interrupt tasks rather than
replaying work. All lease timestamps use the PostgreSQL server clock.
"""
import argparse
import json
import logging
import os
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID,uuid4

from .isolation import _limit,ResultReader,cleanup_child
from storage.versions import materialize,archive_inputs

KINDS={"spectral_index","spectral_change","semantic_segmentation"}
_LEASE=30
_LOG=logging.getLogger(__name__)

class Broker:
    def __init__(self,dsn,queue="default"):
        if not isinstance(queue,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",queue):
            raise ValueError("Invalid distributed queue name.")
        self.dsn=dsn
        self.queue=queue
        with self.connect() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('geofathom-distributed-schema'))")
            c.execute("""CREATE TABLE IF NOT EXISTS gf_distributed_jobs(
                id TEXT PRIMARY KEY,queue TEXT NOT NULL,client TEXT NOT NULL,
                client_until TIMESTAMPTZ NOT NULL,worker TEXT,node TEXT,
                worker_until TIMESTAMPTZ,status TEXT NOT NULL,spec JSONB NOT NULL,
                result JSONB,error TEXT,created TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated TIMESTAMPTZ NOT NULL DEFAULT now())""")
            c.execute("""CREATE INDEX IF NOT EXISTS gf_distributed_queue
                ON gf_distributed_jobs(queue,status,created)""")

    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=5)

    def submit(self,spec):
        if spec.get("kind") not in KINDS:
            raise ValueError("Distributed workers accept only pure local raster analysis.")
        data=json.dumps(spec,allow_nan=False)
        if len(data.encode())>100_000:
            raise ValueError("Distributed task specification too large.")
        from psycopg.types.json import Jsonb
        uid,token=str(uuid4()),str(uuid4())
        with self.connect() as c:
            c.execute("""INSERT INTO gf_distributed_jobs(id,queue,client,client_until,status,spec)
                VALUES(%s,%s,%s,now()+interval '30 seconds','queued',%s)""",
                (uid,self.queue,token,Jsonb(spec)))
        return uid,token

    def recover(self,c):
        c.execute("""UPDATE gf_distributed_jobs SET status='interrupted',
            error='Coordinator or compute lease expired.',updated=now()
            WHERE queue=%s AND status IN ('queued','running') AND
            (client_until<now() OR (status='running' AND worker_until<now()))""",(self.queue,))

    def claim(self,node):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}",node):
            raise ValueError("Invalid compute node identifier.")
        owner=str(uuid4())
        with self.connect() as c:
            self.recover(c)
            # One execution slot per named node, enforced across processes.
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",
                      (self.queue,node))
            if c.execute("""SELECT id FROM gf_distributed_jobs WHERE queue=%s
                AND node=%s AND status='running' AND worker_until>now()
                AND client_until>now() LIMIT 1""",(self.queue,node)).fetchone():
                return None
            row=c.execute("""SELECT id,spec FROM gf_distributed_jobs
                WHERE queue=%s AND status='queued' AND client_until>now()
                ORDER BY created,id FOR UPDATE SKIP LOCKED LIMIT 1""",(self.queue,)).fetchone()
            if row is None:
                return None
            c.execute("""UPDATE gf_distributed_jobs SET status='running',worker=%s,node=%s,
                worker_until=now()+interval '30 seconds',updated=now() WHERE id=%s""",
                (owner,node,row["id"]))
            return row["id"],owner,row["spec"]

    def poll(self,uid,token):
        with self.connect() as c:
            self.recover(c)
            row=c.execute("""UPDATE gf_distributed_jobs SET
                client_until=now()+interval '30 seconds' WHERE id=%s AND queue=%s AND client=%s
                AND (client_until>now() OR status NOT IN ('queued','running'))
                RETURNING status,result,error""",(uid,self.queue,token)).fetchone()
        if row is None:
            raise RuntimeError("Distributed coordinator lease lost.")
        return row

    def heartbeat(self,uid,owner):
        with self.connect() as c:
            return c.execute("""UPDATE gf_distributed_jobs SET worker_until=now()+interval '30 seconds',
                updated=now() WHERE id=%s AND queue=%s AND worker=%s AND status='running'
                AND worker_until>=now() AND client_until>=now()""",(uid,self.queue,owner)).rowcount==1

    def finish(self,uid,owner,result=None,error=None):
        from psycopg.types.json import Jsonb
        if error is None and len(json.dumps(result,allow_nan=False).encode())>5_000_000:
            error="Distributed result exceeds 5 MB.";result=None
        with self.connect() as c:
            return c.execute("""UPDATE gf_distributed_jobs SET status=%s,result=%s,error=%s,updated=now()
                WHERE id=%s AND queue=%s AND worker=%s AND status='running'
                AND worker_until>=now() AND client_until>=now()""",
                ("failed" if error is not None else "completed",Jsonb(result) if error is None else None,
                 str(error)[:250] if error is not None else None,uid,self.queue,owner)).rowcount==1

    def cancel(self,uid,token):
        with self.connect() as c:
            c.execute("""UPDATE gf_distributed_jobs SET status='cancelled',updated=now()
                WHERE id=%s AND queue=%s AND client=%s AND status IN ('queued','running')""",
                (uid,self.queue,token))

    def prune(self,days=30):
        if type(days) is not int or not 1<=days<=3650:
            raise ValueError("Invalid distributed retention period.")
        with self.connect() as c:
            return c.execute("""DELETE FROM gf_distributed_jobs WHERE queue=%s
                AND status NOT IN ('queued','running')
                AND updated<now()-(%s*interval '1 day')""",(self.queue,days)).rowcount

def configured_broker():
    dsn=os.getenv("GEOFATHOM_DISTRIBUTED_DSN")
    if not dsn:
        raise RuntimeError("Distributed PostgreSQL DSN is not configured.")
    return Broker(dsn,os.getenv("GEOFATHOM_DISTRIBUTED_QUEUE","default"))

def dispatch(kind,payload,provenance,progress):
    root=os.getenv("GEOFATHOM_VERSION_DIR")
    if not root:
        raise RuntimeError("Distributed analysis requires a shared GEOFATHOM_VERSION_DIR.")
    archive_inputs(root,provenance)
    broker=configured_broker()
    uid,token=broker.submit({"kind":kind,"payload":payload,"provenance":provenance})
    started=time.monotonic()
    try:
        while True:
            row=broker.poll(uid,token)
            if row["status"]=="completed":
                progress(1.);return row["result"]
            if row["status"] not in ("queued","running"):
                raise RuntimeError(row["error"] or "Distributed task did not complete.")
            if time.monotonic()-started>_limit("GEOFATHOM_RASTER_TIMEOUT_SECONDS",900,30,7200):
                raise RuntimeError("Distributed analysis timed out.")
            progress(.2)
            time.sleep(.5)
    finally:
        # During a network outage, cancellation may fail. Preserve the original
        # task outcome; server-clock lease expiry still fences the remote worker.
        try:
            broker.cancel(uid,token)
        except Exception:
            _LOG.warning("Distributed cancellation unavailable; relying on lease expiry.", exc_info=True)

def _remote_child(send,spec,root,scratch):
    """Decode only pure compute specs. All inputs are verified private copies."""
    from storage.snapshots import _image_paths,_model_root
    from jobs.queue import _execute_impl
    os.environ["GEOFATHOM_RASTER_TEMP_DIR"]=scratch
    base=Path(scratch)
    provenance=spec["provenance"]
    kind=spec["kind"]
    try:
        from .hard_limits import enforce
        enforce('distributed:'+str(Path(root).resolve()))
        from .resources import configure_child
        configure_child(0)
        if kind not in KINDS:
            raise ValueError("Unsupported remote computation.")
        paths={}
        size=0
        from storage.versions import object_path
        digests=list(provenance["source_sha256"].values())+list(provenance["model_files_sha256"].values())
        for digest in digests:
            size+=object_path(root,digest).stat().st_size
        budget=_limit("GEOFATHOM_SNAPSHOT_LIMIT_MB",16384,64,32768)*1024*1024
        import shutil
        if size>budget or shutil.disk_usage(base).free<size+32*1024*1024:
            raise RuntimeError("Remote node has insufficient snapshot capacity.")
        for uid,digest in provenance["source_sha256"].items():
            if str(UUID(uid))!=uid:
                raise ValueError("Invalid image identifier.")
            target=base/(uid+".tif")
            materialize(root,digest,target);paths[uid]=target
        for name,digest in provenance["model_files_sha256"].items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.(onnx|json)",name):
                raise ValueError("Invalid model filename.")
            materialize(root,digest,base/name)
        it=_image_paths.set(paths)
        mt=_model_root.set(base if provenance["model_files_sha256"] else None)
        try:
            outcome=_execute_impl(kind,None,spec["payload"])
        finally:
            _image_paths.reset(it);_model_root.reset(mt)
        data=json.dumps({"status":"ok","result":outcome},allow_nan=False).encode()
        if len(data)>5_000_100:
            raise RuntimeError("Distributed output too large.")
        send.send_bytes(data)
    except Exception as error:
        send.send_bytes(json.dumps({"status":"error","error":str(error)[:250]}).encode())
    finally:
        send.close()

def worker_once(broker,node,root):
    claimed=broker.claim(node)
    if not claimed:
        return False
    uid,owner,spec=claimed
    import multiprocessing
    import psutil
    context=multiprocessing.get_context("spawn")
    with TemporaryDirectory(prefix="geofathom-remote-") as scratch:
        receive,send=context.Pipe(duplex=False)
        process=context.Process(target=_remote_child,args=(send,spec,str(root),scratch))
        reader=None
        try:
            process.start();send.close()
            reader=ResultReader(receive)
            started=time.monotonic();renewed=started
            timeout=_limit("GEOFATHOM_RASTER_TIMEOUT_SECONDS",900,30,7200)
            budget=_limit("GEOFATHOM_RASTER_RSS_MB",2048,256,16384)*1024*1024
            monitor=psutil.Process(process.pid)
            while True:
                now=time.monotonic()
                if now-renewed>=2:
                    if not broker.heartbeat(uid,owner):
                        raise RuntimeError("Distributed node lease lost.")
                    renewed=now
                if now-started>timeout:
                    raise RuntimeError("Remote subprocess exceeded wall-time budget.")
                if reader.ready.wait(.15) or (not process.is_alive() and reader.ready.wait(.15)):
                    if time.monotonic()-started>timeout:
                        raise RuntimeError("Remote subprocess exceeded wall-time budget.")
                    result=reader.get()
                    if not broker.finish(uid,owner,result=result):
                        raise RuntimeError("Remote node no longer owns the task.")
                    break
                if not process.is_alive():
                    # The pipe reader is still bounded by the watchdog.
                    if reader.ready.wait(.15):
                        continue
                    raise RuntimeError("Remote subprocess stopped without a result.")
                try:
                    if monitor.memory_info().rss>budget:
                        raise RuntimeError("Remote subprocess exceeded CPU RSS budget.")
                except psutil.NoSuchProcess:
                    continue
        except Exception as error:
            # The database can disappear during heartbeat/result publication.
            # Never keep a child running or overwrite another owner's result.
            try:
                broker.finish(uid,owner,error=str(error))
            except Exception:
                _LOG.warning("Distributed failure publication unavailable; lease will expire.", exc_info=True)
        finally:
            cleanup_child(process,receive,send,reader)
    return True

def main():
    parser=argparse.ArgumentParser(description="Run a PostgreSQL-backed raster compute node")
    parser.add_argument("--node",default=os.getenv("GEOFATHOM_NODE_ID",os.getenv("COMPUTERNAME") or __import__("socket").gethostname()))
    parser.add_argument("--cleanup-days",type=int)
    args=parser.parse_args()
    broker=configured_broker()
    if args.cleanup_days:
        print("Removed",broker.prune(args.cleanup_days),"terminal broker tasks")
        return
    root=os.environ["GEOFATHOM_VERSION_DIR"]
    try:
        while True:
            if not worker_once(broker,args.node,root):
                time.sleep(.5)
    except KeyboardInterrupt:
        pass

if __name__=="__main__":
    main()
