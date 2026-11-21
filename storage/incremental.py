"""Transactional, content-addressed SQLite backup generations.

Each generation describes a consistent SQLite Online Backup snapshot.
Only new chunks are stored; deleted generations can be garbage-collected
without breaking any retained generation. Restore verifies every chunk and
the full snapshot before invoking the normal database integrity checks.
"""
import argparse
from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

CHUNK_BYTES=65536
MAX_BYTES=16*1024**3

def _open(archive):
    path=Path(archive).resolve()
    from storage.database import database_path
    if path==database_path().resolve():
        raise ValueError("Backup archive must differ from the live database.")
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=60)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS archive_chunks(
            digest TEXT PRIMARY KEY,content BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS archive_generations(
            id TEXT PRIMARY KEY,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            bytes INTEGER NOT NULL,digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS archive_manifest(
            generation TEXT NOT NULL REFERENCES archive_generations(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,digest TEXT NOT NULL REFERENCES archive_chunks(digest),
            PRIMARY KEY(generation,ordinal));
        CREATE INDEX IF NOT EXISTS archive_manifest_digest ON archive_manifest(digest);
        """)
        return db
    except BaseException:
        db.close()
        raise

def capture(archive,retain=7):
    if type(retain) is not int or not 1<=retain<=365:
        raise ValueError("Retention must be 1–365 generations.")
    from .maintenance import backup_database
    with TemporaryDirectory(prefix="geo-backup-") as temp:
        snapshot=Path(backup_database(Path(temp)/"snapshot.sqlite"))
        size=snapshot.stat().st_size
        if not 0<size<=MAX_BYTES:
            raise ValueError("Snapshot exceeds incremental backup size limit.")
        revision=uuid4().hex
        digest=sha256()
        inserted=0
        with closing(_open(archive)) as db,db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO archive_generations(id,bytes,digest) VALUES(?,?,?)",
                       (revision,size,"pending"))
            with snapshot.open("rb") as inp:
                for ordinal,block in enumerate(iter(lambda:inp.read(CHUNK_BYTES),b"")):
                    digest.update(block)
                    key=sha256(block).hexdigest()
                    changed=db.execute("INSERT OR IGNORE INTO archive_chunks VALUES(?,?)",
                                       (key,block)).rowcount
                    if changed:
                        inserted+=len(block)
                    else:
                        stored=db.execute("SELECT content FROM archive_chunks WHERE digest=?",
                                          (key,)).fetchone()[0]
                        if stored!=block:
                            raise RuntimeError("Existing backup chunk failed verification.")
                    db.execute("INSERT INTO archive_manifest VALUES(?,?,?)",(revision,ordinal,key))
            db.execute("UPDATE archive_generations SET digest=? WHERE id=?",
                       (digest.hexdigest(),revision))
            # rowid is the committed generation order, even within one second.
            db.execute("""DELETE FROM archive_generations WHERE id IN
                (SELECT id FROM archive_generations ORDER BY rowid DESC LIMIT -1 OFFSET ?)""",
                (retain,))
            db.execute("""DELETE FROM archive_chunks WHERE NOT EXISTS
                (SELECT 1 FROM archive_manifest m WHERE m.digest=archive_chunks.digest)""")
        return {"generation":revision,"snapshot_bytes":size,"new_chunk_bytes":inserted,
                "sha256":digest.hexdigest()}

def generations(archive):
    with closing(_open(archive)) as db:
        return [{"id":r[0],"created":r[1],"bytes":r[2],"sha256":r[3]}
                for r in db.execute("""SELECT id,created,bytes,digest
                    FROM archive_generations ORDER BY rowid DESC""")]

def restore(archive,generation,destination):
    from .maintenance import restore_to_new_database
    if not Path(archive).is_file():
        raise FileNotFoundError("Incremental backup archive is missing.")
    with TemporaryDirectory(prefix="geo-restore-") as temp:
        snapshot=Path(temp)/"snapshot.sqlite"
        with closing(_open(archive)) as db,db:
            # A read transaction pins the generation against retention pruning.
            db.execute("BEGIN")
            row=db.execute("SELECT bytes,digest FROM archive_generations WHERE id=?",
                           (generation,)).fetchone()
            if row is None:
                raise ValueError("Backup generation does not exist.")
            size,expected=row
            if not 0<size<=MAX_BYTES:
                raise RuntimeError("Invalid snapshot length.")
            digest=sha256()
            total=0
            with snapshot.open("xb") as out:
                rows=db.execute("""SELECT m.ordinal,m.digest,c.content FROM archive_manifest m
                    JOIN archive_chunks c ON m.digest=c.digest
                    WHERE m.generation=? ORDER BY m.ordinal""",(generation,))
                for index,(ordinal,key,block) in enumerate(rows):
                    length=min(CHUNK_BYTES,size-total)
                    if ordinal!=index or length<=0 or len(block)!=length or sha256(block).hexdigest()!=key:
                        raise RuntimeError("Incremental backup chunk is corrupt or missing.")
                    digest.update(block);total+=len(block);out.write(block)
            if total!=size or digest.hexdigest()!=expected:
                raise RuntimeError("Incremental backup snapshot failed verification.")
        return restore_to_new_database(snapshot,destination)

def main():
    parser=argparse.ArgumentParser(description="Incremental SQLite backup archive")
    parser.add_argument("archive",type=Path)
    commands=parser.add_subparsers(dest="command",required=True)
    save=commands.add_parser("capture");save.add_argument("--retain",type=int,default=7)
    save.add_argument("--interval",type=int,default=0)
    commands.add_parser("list")
    recovery=commands.add_parser("restore");recovery.add_argument("generation");recovery.add_argument("destination",type=Path)
    args=parser.parse_args()
    if args.command=="capture":
        if args.interval and not 60<=args.interval<=86400:
            parser.error("Backup interval must be 60–86400 seconds.")
        import time
        while True:
            print(capture(args.archive,args.retain),flush=True)
            if not args.interval:break
            time.sleep(args.interval)
    elif args.command=="list":
        import json
        print(json.dumps(generations(args.archive),indent=2))
    else:
        print(restore(args.archive,args.generation,args.destination))
if __name__=="__main__":
    main()
