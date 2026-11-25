"""Durable, source-addressed tile reductions for interrupted slope studies."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .cancellation import checkpoint
from imagery.raster import RasterError


def source_identity(source,cancel=None):
    # Include GDAL auxiliary files because masks and georeferencing can
    # change even when the primary TIFF itself has not changed.
    files=sorted(set(source.files))
    digest=hashlib.sha256()
    signature=[]
    for filename in files:
        path=Path(filename)
        if not path.is_file():
            raise RasterError("Persistent terrain checkpoints require local source files.")
        before=path.stat()
        digest.update(str(path.name).encode()+b"\0")
        with path.open("rb") as handle:
            while True:
                checkpoint(cancel)
                block=handle.read(4*1024**2)
                if not block:break
                digest.update(block)
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise RasterError("Source DEM changed during checkpoint identification.")
        signature.append((str(path),after.st_size,after.st_mtime_ns))
    return digest.hexdigest(),signature


def verify_source(signature):
    for filename,size,mtime in signature:
        stat=Path(filename).stat()
        if (stat.st_size,stat.st_mtime_ns)!=(size,mtime):
            raise RasterError("Source DEM changed during terrain analysis.")


@contextmanager
def slope_checkpoint(source,polygon,window,block,method,root,cancel=None):
    digest,signature=source_identity(source,cancel)
    # Include numerical implementation version, geometry, window, CRS and
    # tile order. Resource changes that alter partitioning start a fresh run.
    descriptor=["slope-halo-v1",digest,polygon,
                [window.col_off,window.row_off,window.width,window.height],
                list(source.transform),str(source.crs),block,method]
    key=hashlib.sha256(json.dumps(descriptor,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/"slope-checkpoints.sqlite",timeout=30)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS slope_tiles (task TEXT, ordinal INTEGER, stats TEXT NOT NULL, touched INTEGER NOT NULL, PRIMARY KEY(task,ordinal))")
        # Keep stale abandoned checkpoints bounded, without touching current runs.
        db.execute("DELETE FROM slope_tiles WHERE touched<?",(int(time.time())-7*86400,))
        db.commit()
        class Store:
            def load(self,ordinal):
                row=db.execute("SELECT stats FROM slope_tiles WHERE task=? AND ordinal=?",(key,ordinal)).fetchone()
                return json.loads(row[0]) if row else None
            def save(self,ordinal,stats):
                db.execute("INSERT OR REPLACE INTO slope_tiles VALUES (?,?,?,?)",
                           (key,ordinal,json.dumps(stats,allow_nan=False),int(time.time())))
                db.commit()
            def finish(self):
                verify_source(signature)
                db.execute("DELETE FROM slope_tiles WHERE task=?",(key,))
                db.commit()
        yield Store()
    finally:
        db.close()
