"""SQLite-backed cross-process job leases and global raster/GPU slots.

SQLite is authoritative; no process can commit a result after losing its lease.
Each work item is at-most-one *active* owner. Stale tasks are interrupted,
never automatically re-executed if a side effect may have happened.
"""
import os
import sqlite3
import time
from uuid import uuid4

LEASE_SECONDS = 30.0
PROCESS_ID = str(uuid4())
RASTER_KINDS = {"spectral_index", "spectral_change", "semantic_segmentation", "stac_ndvi", "remote_windowed", "remote_cube"}


def ensure_lease_schema(connection):
    # Existing local databases are migrated in place without deleting jobs.
    fields = {row[1] for row in connection.execute("PRAGMA table_info(gis_jobs)")}
    for name, definition in (
        ("lease_owner", "TEXT"),
        ("lease_expires", "REAL"),
        ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in fields:
            connection.execute(f"ALTER TABLE gis_jobs ADD COLUMN {name} {definition}")
    connection.execute("""CREATE INDEX IF NOT EXISTS gis_jobs_lease_status
        ON gis_jobs(status,lease_expires)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS gis_job_slots (
        name TEXT PRIMARY KEY, owner TEXT, expires REAL NOT NULL DEFAULT 0
    )""")
    connection.executemany("""INSERT OR IGNORE INTO gis_job_slots(name,owner,expires)
        VALUES(?,NULL,0)""",[("raster",),("inference",),("accelerator",)])
    # All processes sharing this local database use one persisted capacity.
    # Reject inconsistent configuration rather than allocating extra slots.
    connection.execute("""CREATE TABLE IF NOT EXISTS gis_job_config(
        key TEXT PRIMARY KEY, value INTEGER NOT NULL)""")
    count=int(os.getenv("GEOFATHOM_COMPUTE_SLOTS","2"))
    if not 1<=count<=8:
        raise ValueError("Compute slots must be 1–8.")
    connection.execute("INSERT OR IGNORE INTO gis_job_config VALUES('compute_slots',?)",(count,))
    saved=connection.execute("SELECT value FROM gis_job_config WHERE key='compute_slots'").fetchone()[0]
    if saved!=count:
        raise ValueError("Compute slot configuration differs from this database.")
    connection.executemany("""INSERT OR IGNORE INTO gis_job_slots(name,owner,expires)
        VALUES(?,NULL,0)""",[(f"compute:{i}",) for i in range(count)])


def recover_expired(connection, now=None):
    """Mark only expired owners interrupted, never a live worker in another process."""
    now=time.time() if now is None else now
    connection.execute("""UPDATE gis_jobs SET status='interrupted',
        error='Worker lease expired; result may be incomplete. Resubmit explicitly.',
        lease_owner=NULL,lease_expires=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE status='running' AND (lease_expires IS NULL OR lease_expires<?)""",(now,))
    connection.execute("""UPDATE gis_job_slots SET owner=NULL,expires=0
        WHERE expires<?""",(now,))


def _resources(kind,payload):
    result=[]
    if kind in RASTER_KINDS and (payload.get("full_resolution") is True or kind in {"remote_windowed","remote_cube"}):
        result.append("raster")
    if kind=="semantic_segmentation":
        result.append("inference")
    if ((kind=="semantic_segmentation" and
            os.getenv("GEOFATHOM_VISION_DEVICE","cpu").lower()=="cuda")
            or (kind in {"spectral_index","spectral_change","stac_ndvi"} and
            os.getenv("GEOFATHOM_SPECTRAL_DEVICE","cpu").lower() in ("cuda","auto"))):
        result.append("accelerator")
    return result


def claim(connection,uid,owner,now=None):
    """Atomically claim a queued task and its optional global raster slot."""
    now=time.time() if now is None else now
    # An immediate write lock ensures concurrent processes cannot both
    # accept the same queue row or take the global raster slot.
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    row=connection.execute("""SELECT * FROM gis_jobs WHERE id=?""",(uid,)).fetchone()
    if row is None or row["status"]!="queued":
        return None
    if row["cancel_requested"]:
        connection.execute("""UPDATE gis_jobs SET status='cancelled',
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id=?""",(uid,))
        return None
    import json
    payload=json.loads(row["payload"])
    slot=connection.execute("""SELECT name FROM gis_job_slots
        WHERE name LIKE 'compute:%' AND (owner IS NULL OR expires<?)
        ORDER BY name LIMIT 1""",(now,)).fetchone()
    if slot is None:
        return None
    resources=[slot[0],*_resources(row["kind"],payload)]
    for resource in resources:
        acquired=connection.execute("""UPDATE gis_job_slots
            SET owner=?,expires=? WHERE name=?
            AND (owner IS NULL OR expires<?)""",
            (owner,now+LEASE_SECONDS,resource,now))
        if acquired.rowcount!=1:
            release_slot(connection,owner)
            return None
    updated=connection.execute("""UPDATE gis_jobs SET status='running',
        progress=10,lease_owner=?,lease_expires=?,attempts=attempts+1,
        updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE id=? AND status='queued'""",
        (owner,now+LEASE_SECONDS,uid))
    if updated.rowcount!=1:
        release_slot(connection,owner)
        return None
    return dict(row)


def heartbeat(connection,uid,owner,now=None):
    """Return False if cancellation, expiration, or reassignment removed ownership."""
    now=time.time() if now is None else now
    row=connection.execute("""SELECT lease_expires,cancel_requested,kind,payload
        FROM gis_jobs WHERE id=? AND lease_owner=? AND status='running'""",
        (uid,owner)).fetchone()
    if not row or row["lease_expires"]<now:
        return False
    import json
    payload=json.loads(row["payload"])
    slot=connection.execute("""SELECT name FROM gis_job_slots
        WHERE name LIKE 'compute:%' AND owner=? AND expires>=?""",
        (owner,now)).fetchone()
    if slot is None:
        return False
    resources=[slot[0],*_resources(row["kind"],payload)]
    for resource in resources:
        updated=connection.execute("""UPDATE gis_job_slots
            SET expires=? WHERE name=? AND owner=? AND expires>=?""",
            (now+LEASE_SECONDS,resource,owner,now))
        if updated.rowcount!=1:
            return False
    return connection.execute("""UPDATE gis_jobs SET lease_expires=?
        WHERE id=? AND lease_owner=? AND status='running'""",
        (now+LEASE_SECONDS,uid,owner)).rowcount==1


def is_owner(connection,uid,owner,now=None):
    now=time.time() if now is None else now
    row=connection.execute("""SELECT lease_owner,lease_expires FROM gis_jobs
        WHERE id=? AND status='running'""",(uid,)).fetchone()
    return bool(row and row["lease_owner"]==owner and row["lease_expires"]>=now)


def release_slot(connection,owner):
    connection.execute("""UPDATE gis_job_slots SET owner=NULL,expires=0
        WHERE owner=?""",(owner,))


def prune_old_jobs(connection,days=30,now=None):
    """Delete completed/failed/cancelled/interrupted job history and result rows."""
    if not isinstance(days,int) or not 1<=days<=3650:
        raise ValueError("Retention must be 1–3650 days.")
    from datetime import datetime,timezone,timedelta
    cutoff=(datetime.fromtimestamp(now,timezone.utc) if now is not None
            else datetime.now(timezone.utc))-timedelta(days=days)
    deleted=connection.execute("""DELETE FROM gis_jobs
        WHERE status IN ('completed','failed','cancelled','interrupted')
        AND updated_at < ?""",(cutoff.isoformat(),))
    return deleted.rowcount
