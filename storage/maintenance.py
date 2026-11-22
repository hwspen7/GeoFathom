"""Operator-only database backup, spatial-index reconciliation and integrity audit.

SQLite Online Backup API creates a coherent snapshot even with WAL activity.
Never copy the database file directly during active writes.
"""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from storage.database import _connect,database_path
from storage.paging import prepare_rtree
from imagery.store import imagery_dir,file_sha256


def backup_database(destination):
    destination=Path(destination).expanduser().resolve()
    source=database_path().resolve()
    if destination==source:
        raise ValueError("Backup destination must differ from source.")
    if not source.is_file():
        raise ValueError("Backup source database does not exist.")
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.with_suffix(destination.suffix+".tmp")
    if temp.exists():
        raise ValueError("Temporary backup target already exists.")
    try:
        # sqlite3.Connection.__exit__ commits but does not CLOSE the file.
        # Explicit closing is required for atomic rename on Windows.
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)) as original:
            with closing(sqlite3.connect(temp)) as target:
                original.backup(target,pages=100,sleep=.05)
                row=target.execute("PRAGMA integrity_check").fetchone()
                if not row or row[0]!="ok":
                    raise RuntimeError("Backed-up database failed integrity check.")
                target.commit()
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return str(destination)


def restore_to_new_database(backup,destination):
    """Recover to an unused database path, never replace an active WAL database."""
    import os
    backup=Path(backup).expanduser().resolve(strict=True)
    destination=Path(destination).expanduser().resolve()
    if destination.exists() or destination==database_path().resolve():
        raise ValueError("Restore destination already exists or is the active database.")
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Use exclusive creation so concurrent restore attempts cannot overwrite.
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(backup.as_uri()+"?mode=ro",uri=True)) as source:
            if source.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise RuntimeError("Backup failed integrity check.")
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise RuntimeError("Restored database failed integrity check.")
                if target.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Restored database has broken foreign keys.")
                # Validate this is a GeoFathom database, not just any SQLite file.
                for name in ("projects","features"):
                    if not target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone():
                        raise RuntimeError("Backup is not a GeoFathom database.")
                target.commit()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)


def verify_spatial_indexes(repair=False):
    with _connect() as c:
        missing=c.execute("""SELECT count(*) FROM features f
            LEFT JOIN feature_bounds b ON b.feature_rowid=f.rowid
            WHERE b.feature_rowid IS NULL""").fetchone()[0]
        extra=c.execute("""SELECT count(*) FROM feature_bounds b
            LEFT JOIN features f ON f.rowid=b.feature_rowid
            WHERE f.rowid IS NULL""").fetchone()[0]
        if repair and (missing or extra):
            prepare_rtree(c)
            missing_after=c.execute("""SELECT count(*) FROM features f
                LEFT JOIN feature_bounds b ON b.feature_rowid=f.rowid
                WHERE b.feature_rowid IS NULL""").fetchone()[0]
            extra_after=c.execute("""SELECT count(*) FROM feature_bounds b
                LEFT JOIN features f ON f.rowid=b.feature_rowid
                WHERE f.rowid IS NULL""").fetchone()[0]
        else:
            missing_after,extra_after=missing,extra
    return {"missing_before":missing,"extra_before":extra,
            "missing_after":missing_after,"extra_after":extra_after,
            "repaired":bool(repair and (missing or extra))}


def audit_imagery():
    root=imagery_dir()
    if not root.exists():
        return {"checked":0,"mismatches":[]}
    bad=[]
    checked=0
    for sidecar in root.glob("*.json"):
        image=sidecar.with_suffix(".tif")
        if not image.is_file():
            bad.append(sidecar.stem+":missing-image")
            continue
        checked+=1
        try:
            info=json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(info,dict):
                raise ValueError("Sidecar must be an object.")
            expected=info.get("sha256")
            if expected and expected!=file_sha256(image):
                bad.append(sidecar.stem+":sha256-mismatch")
        except (OSError,ValueError,UnicodeError):
            bad.append(sidecar.stem+":invalid-sidecar")
    return {"checked":checked,"mismatches":bad}


def backup_rotation(directory,retain=7):
    """Create one verified backup, then prune only this command's old snapshots."""
    from datetime import datetime,timezone
    from uuid import uuid4
    import re
    if type(retain) is not int or not 1<=retain<=365:
        raise ValueError("Backup retention count must be 1–365.")
    root=Path(directory).expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest=root/f"geofathom-{stamp}-{uuid4().hex[:8]}.sqlite"
    backup_database(dest)
    owned=[p for p in root.glob("geofathom-*.sqlite") if
           re.fullmatch(r"geofathom-\d{8}T\d{12}Z-[a-f0-9]{8}\.sqlite",p.name)
           and p.is_file() and not p.is_symlink()]
    removed=[]
    for path in sorted(owned,reverse=True)[retain:]:
        path.unlink(missing_ok=True);removed.append(path.name)
    return {"backup":str(dest),"pruned":removed}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--backup",type=Path)
    parser.add_argument("--backup-dir",type=Path)
    parser.add_argument("--retain",type=int,default=7)
    parser.add_argument("--interval",type=int,default=0,help="Repeat rotating backup every N seconds (0 = once)")
    parser.add_argument("--restore-from",type=Path)
    parser.add_argument("--restore-to",type=Path)
    parser.add_argument("--verify",action="store_true")
    parser.add_argument("--repair-index",action="store_true")
    parser.add_argument("--audit-imagery",action="store_true")
    args=parser.parse_args()
    results={}
    if args.interval and (not args.backup_dir or not 60<=args.interval<=86400):
        parser.error("Periodic backup requires --backup-dir and an interval of 60–86400 seconds.")
    if args.backup_dir:
        results["rotation"]=backup_rotation(args.backup_dir,args.retain)
        if args.interval:
            import time
            try:
                while True:
                    print(json.dumps(results),flush=True)
                    time.sleep(args.interval)
                    results["rotation"]=backup_rotation(args.backup_dir,args.retain)
            except KeyboardInterrupt:
                return
    if bool(args.restore_from)!=bool(args.restore_to):
        parser.error("Use --restore-from and --restore-to together.")
    if args.restore_from:
        results["restored"]=restore_to_new_database(args.restore_from,args.restore_to)
    if args.backup:results["backup"]=backup_database(args.backup)
    if args.verify or args.repair_index:
        results["spatial_index"]=verify_spatial_indexes(args.repair_index)
    if args.audit_imagery:results["imagery"]=audit_imagery()
    if not results:parser.error("Choose a database or imagery maintenance operation.")
    print(json.dumps(results,indent=2))


if __name__=="__main__":
    main()
