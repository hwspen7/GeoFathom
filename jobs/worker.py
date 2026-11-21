"""Opt-in external worker and offline retention maintenance.

Run API nodes with GEOFATHOM_EXTERNAL_WORKER=1 and start one or more:
    python -m jobs.worker --poll 0.5
SQLite claim/lease/slot transactions coordinate all processes that share
the SAME local database file and filesystem; no networked SQLite over NFS.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Event
import time

from storage.database import _connect,database_path
from .leases import ensure_lease_schema,recover_expired,prune_old_jobs


def run_worker(poll=1.,stop=None,max_workers=2):
    if not .05<=poll<=30 or not 1<=max_workers<=8:
        raise ValueError("Invalid worker polling/capacity parameters.")
    # Do not start the API's internal submission threads in this process.
    os.environ["GEOFATHOM_EXTERNAL_WORKER"]="1"
    from .queue import _schema,_worker
    db=str(database_path().resolve())
    stop=stop or Event()
    running={}
    with ThreadPoolExecutor(max_workers=max_workers,
                            thread_name_prefix="geofathom-external") as pool:
        while not stop.is_set():
            for uid,future in list(running.items()):
                if future.done():
                    future.result()
                    del running[uid]
            with _connect() as connection:
                _schema(connection)
                recover_expired(connection)
                if len(running)<max_workers:
                    pending=[r[0] for r in connection.execute(
                        """SELECT id FROM gis_jobs WHERE status='queued'
                        AND cancel_requested=0 ORDER BY created_at,id LIMIT ?""",
                        (max_workers-len(running),)).fetchall()]
                else:
                    pending=[]
            for uid in pending:
                if uid not in running:
                    running[uid]=pool.submit(_worker,uid,db)
            stop.wait(poll)


def cleanup(days):
    from .queue import _schema
    with _connect() as conn:
        _schema(conn)
        return prune_old_jobs(conn,days)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--poll",type=float,default=1.)
    parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--cleanup-days",type=int,default=None,
                        help="Purge terminal job rows and their result records")
    args=parser.parse_args()
    if args.cleanup_days is not None:
        print("Removed",cleanup(args.cleanup_days),"expired jobs")
    else:
        print("GeoFathom shared-SQLite worker started")
        try:
            run_worker(args.poll,max_workers=args.workers)
        except KeyboardInterrupt:
            pass


if __name__=="__main__":
    main()
