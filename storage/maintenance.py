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
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.with_suffix(destination.suffix+".tmp")
    if temp.exists():
        raise ValueError("Temporary backup target already exists.")
    try:
        # sqlite3.Connection.__exit__ commits but does not CLOSE the file.
        # Explicit closing is required for atomic rename on Windows.
        with closing(sqlite3.connect(source)) as original:
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
        info=json.loads(sidecar.read_text(encoding="utf-8"))
        expected=info.get("sha256")
        checked+=1
        if expected and expected!=file_sha256(image):
            bad.append(sidecar.stem+":sha256-mismatch")
    return {"checked":checked,"mismatches":bad}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--backup",type=Path)
    parser.add_argument("--verify",action="store_true")
    parser.add_argument("--repair-index",action="store_true")
    parser.add_argument("--audit-imagery",action="store_true")
    args=parser.parse_args()
    results={}
    if args.backup:results["backup"]=backup_database(args.backup)
    if args.verify or args.repair_index:
        results["spatial_index"]=verify_spatial_indexes(args.repair_index)
    if args.audit_imagery:results["imagery"]=audit_imagery()
    if not results:parser.error("Choose a database or imagery maintenance operation.")
    print(json.dumps(results,indent=2))


if __name__=="__main__":
    main()
