"""Exact disk-backed radius-neighborhood aggregation with complete tile halos."""
import sqlite3
import tempfile
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

def tiled_radius_summary(chunks,tile,radius,*,point_limit=10_000_000):
    if not .001<=radius<=tile<=1e6:
        raise ValueError("Tile width must be at least the positive neighborhood radius.")
    with tempfile.TemporaryDirectory(prefix="geofathom-lidar-halo-") as tmp:
        db=sqlite3.connect(Path(tmp)/"points.sqlite")
        try:
            db.execute("CREATE TABLE points (i INTEGER,j INTEGER,k INTEGER,x REAL,y REAL,z REAL)")
            total=0
            for p in chunks:
                if not len(p):continue
                if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all() or np.max(np.abs(p))>1e9:
                    raise ValueError("Invalid point chunk.")
                total+=len(p)
                if total>point_limit:raise ValueError("Tiled input point budget exceeded.")
                keys=np.floor(p/tile).astype(np.int64)
                db.executemany("INSERT INTO points VALUES (?,?,?,?,?,?)",
                    ((*map(int,key),*map(float,row)) for key,row in zip(keys,p)))
            if not total:raise ValueError("Empty point cloud.")
            db.execute("CREATE INDEX tile_index ON points(i,j,k)")
            db.commit()
            tiles=db.execute("SELECT i,j,k,count(*) FROM points GROUP BY i,j,k LIMIT 100001").fetchall()
            if len(tiles)>100000:raise ValueError("Tile output exceeds 100,000; increase tile width.")
            rows=[];halo_work=0
            for i,j,k,number in tiles:
                # Because radius <= tile width, all possible neighbors lie in
                # these 27 tiles. Include exact same-tile points and duplicates.
                where="i BETWEEN ? AND ? AND j BETWEEN ? AND ? AND k BETWEEN ? AND ?"
                args=(i-1,i+1,j-1,j+1,k-1,k+1)
                count=db.execute("SELECT count(*) FROM points WHERE "+where,args).fetchone()[0]
                halo_work+=count
                if count>250000 or halo_work>50_000_000:
                    raise ValueError("Halo work budget exceeded; reduce radius and tile width or crop the cloud.")
                halo=np.asarray(db.execute("SELECT x,y,z FROM points WHERE "+where,args).fetchall(),float)
                core=np.asarray(db.execute("SELECT x,y,z FROM points WHERE i=? AND j=? AND k=?",(i,j,k)).fetchall(),float)
                # Center at the tile origin to preserve local distance precision.
                origin=np.array([i,j,k],float)*tile
                counts=cKDTree(halo-origin).query_ball_point(core-origin,radius,return_length=True)-1
                rows.append([*((np.array([i,j,k],float)+.5)*tile),number,float(counts.mean()),
                    int(counts.min()),int(counts.max()),float(counts.mean()/(4*np.pi*radius**3/3)),int(counts.sum())])
        finally:db.close()
    table=np.asarray(rows,float)
    return table,{"input_points":total,"occupied_tiles":len(table),"tile_width_m":tile,"radius_m":radius,
        "halo_point_visits":halo_work,"directed_neighbor_pairs":int(table[:,-1].sum()),
        "mean_neighbors":float(table[:,-1].sum()/total),
        "assumption":"exact spherical neighborhoods across complete tile halos; no survey-boundary correction"}

def stream_radius(stream,epsg,tile,radius):
    from .lidar_disk import _laspy,_metadata,_points,_digest,MAX_STREAM_POINTS,CHUNK
    digest=_digest(stream);laspy=_laspy()
    try:
        with laspy.open(stream,closefd=False) as reader:
            meta=_metadata(reader.header,epsg)
            if not 0<reader.header.point_count<=MAX_STREAM_POINTS:
                raise ValueError("Streaming point budget exceeded.")
            rows,metrics=tiled_radius_summary((_points(r) for r in reader.chunk_iterator(CHUNK)),tile,radius)
            if metrics["input_points"]!=reader.header.point_count:
                raise ValueError("Point count mismatch.")
    except (laspy.errors.LaspyException,OSError,EOFError,RuntimeError) as exc:
        raise ValueError("LAS/LAZ streaming failed: "+str(exc)) from exc
    metrics["source"]={**meta,"sha256":digest}
    return rows,metrics
