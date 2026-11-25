"""Disk-backed bounded LAS/LAZ voxel statistics and metadata inspection."""
import hashlib
import sqlite3
import tempfile
from pathlib import Path
import numpy as np

MAX_STREAM_POINTS=10_000_000
MAX_STREAM_BYTES=512*1024*1024
MAX_VOXELS=100_000
CHUNK=100_000

def _laspy():
    try:import laspy
    except ImportError as e:raise ValueError("LAS/LAZ extension unavailable; install geofathom-api[lidar].") from e
    return laspy

def _metadata(header,epsg):
    from pyproj import CRS
    embedded=header.parse_crs()
    if embedded is not None:
        horizontal=next((c for c in embedded.sub_crs_list if c.is_projected),embedded)
        if not horizontal.equals(CRS.from_epsg(epsg),ignore_axis_order=True):
            raise ValueError("Embedded horizontal CRS conflicts with the specified EPSG.")
    return {"embedded_crs":embedded.to_string() if embedded else None,
        "las_version":str(header.version),"point_format":int(header.point_format.id),
        "declared_points":int(header.point_count),"compressed":bool(header.are_points_compressed),
        "coordinate_scale":header.scales.tolist(),"coordinate_offset":header.offsets.tolist()}

def _points(record):
    p=np.column_stack((record.x,record.y,record.z)).astype(float,copy=False)
    if not np.isfinite(p).all() or np.max(np.abs(p),initial=0)>1e9:
        raise ValueError("Invalid XYZ coordinates.")
    return p

def _digest(stream):
    stream.seek(0);h=hashlib.sha256();size=0
    while True:
        data=stream.read(1024*1024)
        if not data:break
        size+=len(data)
        if size>MAX_STREAM_BYTES:raise ValueError("File exceeds 512 MiB.")
        h.update(data)
    stream.seek(0)
    return h.hexdigest()

def read_compressed(stream,epsg,max_points):
    laspy=_laspy()
    try:
        with laspy.open(stream,closefd=False) as reader:
            meta=_metadata(reader.header,epsg)
            if not 0<reader.header.point_count<=max_points:
                raise ValueError("Use streaming voxel statistics for clouds above 100,000 points.")
            record=reader.read()
            p=_points(record)
            if len(p)!=reader.header.point_count:raise ValueError("Point count mismatch.")
            cls,n=np.unique(np.asarray(record.classification),return_counts=True)
            meta["classification_counts"]={str(int(c)):int(v) for c,v in zip(cls,n)}
            return p,meta
    except (laspy.errors.LaspyException,OSError,EOFError,RuntimeError) as e:
        raise ValueError("LAS/LAZ decoding failed: "+str(e)) from e

def stream_voxels(stream,epsg,size):
    """Exact voxel counts and additive moments across chunks; disk-backed keys."""
    if not np.isfinite(size) or not .001<=size<=1e6:raise ValueError("Invalid voxel size.")
    digest=_digest(stream)
    laspy=_laspy()
    try:
        with laspy.open(stream,closefd=False) as reader, tempfile.TemporaryDirectory(prefix="geofathom-lidar-") as tmp:
            meta=_metadata(reader.header,epsg)
            if not 0<reader.header.point_count<=MAX_STREAM_POINTS:
                raise ValueError("Streaming limit is 10,000,000 points.")
            count=0;classes={};returns={}
            db=sqlite3.connect(Path(tmp)/"voxels.sqlite")
            try:
                db.execute("CREATE TABLE vox (i INTEGER,j INTEGER,k INTEGER,n INTEGER,sx REAL,sy REAL,sz REAL,lo REAL,hi REAL, PRIMARY KEY(i,j,k)) WITHOUT ROWID")
                sql=("INSERT INTO vox VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(i,j,k) DO UPDATE SET "
                     "n=n+excluded.n,sx=sx+excluded.sx,sy=sy+excluded.sy,sz=sz+excluded.sz,lo=min(lo,excluded.lo),hi=max(hi,excluded.hi)")
                for record in reader.chunk_iterator(CHUNK):
                    p=_points(record);count+=len(p)
                    if count>MAX_STREAM_POINTS:raise ValueError("Point budget exceeded.")
                    for target,values in ((classes,record.classification),(returns,record.return_number)):
                        v,n=np.unique(np.asarray(values),return_counts=True)
                        for label,number in zip(v,n):
                            key=str(int(label));target[key]=target.get(key,0)+int(number)
                    keys,inv,n=np.unique(np.floor(p/size).astype(np.int64),axis=0,return_inverse=True,return_counts=True)
                    # Sum cell-relative coordinates to avoid cancellation at large map origins.
                    local=p-keys[inv]*size
                    sums=np.column_stack([np.bincount(inv,weights=local[:,i]) for i in range(3)])
                    lo=np.full(len(keys),np.inf);hi=np.full(len(keys),-np.inf)
                    np.minimum.at(lo,inv,p[:,2]);np.maximum.at(hi,inv,p[:,2])
                    rows=[(*map(int,key),int(number),*map(float,total),float(a),float(b))
                          for key,number,total,a,b in zip(keys,n,sums,lo,hi)]
                    db.executemany(sql,rows);db.commit()
                    if db.execute("SELECT count(*) FROM vox").fetchone()[0]>MAX_VOXELS:
                        raise ValueError("Occupied voxel budget exceeded; choose a larger voxel size.")
                if count!=reader.header.point_count:raise ValueError("Point count mismatch.")
                result=np.asarray(db.execute("SELECT i,j,k,n,sx,sy,sz,lo,hi FROM vox ORDER BY i,j,k").fetchall(),float)
            finally:db.close()
    except (laspy.errors.LaspyException,OSError,EOFError,RuntimeError) as e:
        raise ValueError("LAS/LAZ streaming failed: "+str(e)) from e
    centroid=result[:,:3]*size+result[:,4:7]/result[:,3,None]
    table=np.column_stack((centroid,result[:,3],result[:,7:9]))
    return table,{"input_points":count,"occupied_voxels":len(table),"voxel_m":size,
        "classification_counts":classes,"return_number_counts":returns,"chunk_points":CHUNK,
        "aggregation":"SQLite disk-backed exact counts; floating-point centroid sums",
        "source":{**meta,"sha256":digest}}
