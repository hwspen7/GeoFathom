"""Native pixel-grid image pyramid and persistent bounded tile cache.

Levels use powers of two relative to the source grid (level 0 = native),
not Web Mercator XYZ. Tile corners are calculated from the source affine.
Cache accounting bounds PNG payloads across processes sharing a local DB;
SQLite page and journal overhead is separate.
"""
from contextlib import closing
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import sqlite3
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from rasterio.warp import transform
from PIL import Image

from .cache import file_identity
from .raster import RasterError,_check

TILE_SIZE=256
MAX_TILE_BYTES=512*1024

class DiskTileCache:
    def __init__(self,path,budget):
        if type(budget) is not int or not 0<=budget<=2*1024**3:
            raise ValueError("Tile cache budget is outside the supported range.")
        self.path=Path(path)
        self.budget=budget

    def _connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(self.path,timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("""CREATE TABLE IF NOT EXISTS tiles(
            key TEXT PRIMARY KEY,png BLOB NOT NULL,size INTEGER NOT NULL,
            accessed INTEGER NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS tiles_lru ON tiles(accessed,key)")
        conn.execute("""CREATE TABLE IF NOT EXISTS config(
            key TEXT PRIMARY KEY,value INTEGER NOT NULL)""")
        conn.execute("INSERT OR IGNORE INTO config VALUES('budget',?)",(self.budget,))
        if conn.execute("SELECT value FROM config WHERE key='budget'").fetchone()[0]!=self.budget:
            conn.close()
            raise ValueError("Tile cache budget differs across processes; use a new cache DB.")
        conn.commit()
        return conn

    def get(self,key,load):
        if self.budget==0:
            return load()
        with closing(self._connect()) as conn:
            row=conn.execute("SELECT png FROM tiles WHERE key=?",(key,)).fetchone()
            if row:
                conn.execute("UPDATE tiles SET accessed=? WHERE key=?",(time.time_ns(),key))
                conn.commit()
                return bytes(row[0])
        png=load()
        if not isinstance(png,bytes):
            raise TypeError("Tile output must contain immutable PNG bytes.")
        if len(png)>min(self.budget,MAX_TILE_BYTES):
            return png
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT png FROM tiles WHERE key=?",(key,)).fetchone()
            if row:
                conn.commit()
                return bytes(row[0])
            size,count=conn.execute("SELECT COALESCE(sum(size),0),count(*) FROM tiles").fetchone()
            while size+len(png)>self.budget or count>=100000:
                victim=conn.execute("SELECT key,size FROM tiles ORDER BY accessed,key LIMIT 1").fetchone()
                if victim is None:
                    break
                conn.execute("DELETE FROM tiles WHERE key=?",(victim[0],))
                size-=victim[1];count-=1
            conn.execute("INSERT INTO tiles VALUES(?,?,?,?)",(key,png,len(png),time.time_ns()))
            conn.commit()
        return png

    def stats(self):
        with closing(self._connect()) as conn:
            size,count=conn.execute("SELECT COALESCE(sum(size),0),count(*) FROM tiles").fetchone()
        return {"payload_bytes":size,"entries":count,"budget_bytes":self.budget}

def levels(width,height):
    maximum=max(0,math.ceil(math.log2(max(width,height)/TILE_SIZE)))
    return [{"level":i,"factor":2**i,
             "columns":math.ceil(width/(TILE_SIZE*2**i)),
             "rows":math.ceil(height/(TILE_SIZE*2**i))}
            for i in range(maximum+1)]

def pyramid_info(path):
    with rasterio.open(path) as src:
        _check(src)
        return {"tile_size":TILE_SIZE,"scheme":"source-pixel-grid",
                "width":src.width,"height":src.height,"levels":levels(src.width,src.height),
                "crs":str(src.crs),"affine":list(src.transform)[:6]}

@lru_cache(maxsize=32)
def _stretch(identity):
    with rasterio.open(identity[0]) as src:
        indexes=[1,2,3] if src.count>=3 else [1]
        values=src.read(indexes,masked=True,
            out_shape=(len(indexes),min(src.height,256),min(src.width,256)),
            resampling=Resampling.average)
        bounds=[]
        for band,dtype in zip(values,[src.dtypes[i-1] for i in indexes]):
            if dtype=="uint8":
                bounds.append((0.,255.));continue
            finite=band.compressed().astype(np.float64)
            finite=finite[np.isfinite(finite)]
            lo,hi=np.percentile(finite,[2,98]) if finite.size else (0.,1.)
            bounds.append((float(lo),float(hi)))
        return tuple(bounds)

def render_tile(path,level,x,y):
    identity=file_identity(path)
    with rasterio.open(path) as src:
        _check(src)
        pyramid=levels(src.width,src.height)
        if (any(type(v) is not int for v in (level,x,y)) or not 0<=level<len(pyramid)
                or not 0<=x<pyramid[level]["columns"] or not 0<=y<pyramid[level]["rows"]):
            raise RasterError("Tile coordinates outside the source pyramid.")
        factor=2**level
        left,top=x*TILE_SIZE*factor,y*TILE_SIZE*factor
        width,height=min(TILE_SIZE*factor,src.width-left),min(TILE_SIZE*factor,src.height-top)
        w,h=math.ceil(width/factor),math.ceil(height/factor)
        indexes=[1,2,3] if src.count>=3 else [1]
        data=src.read(indexes,window=Window(left,top,width,height),masked=True,
                      out_shape=(len(indexes),h,w),resampling=Resampling.bilinear)
        rgb=np.zeros((h,w,3),np.uint8)
        valid=np.ones((h,w),bool)
        for i,(lo,hi) in enumerate(_stretch(identity)):
            band=np.asarray(data[i].data,dtype=np.float64)
            good=~np.ma.getmaskarray(data[i]) & np.isfinite(band)
            valid&=good
            scaled=np.zeros_like(band,dtype=np.uint8)
            if hi>lo:
                scaled[good]=np.clip((band[good]-lo)*255/(hi-lo),0,255).astype(np.uint8)
            if len(indexes)==1:
                rgb[:]=scaled[:,:,None]
            else:
                rgb[:,:,i]=scaled
        rgba=np.zeros((TILE_SIZE,TILE_SIZE,4),np.uint8)
        rgba[:h,:w,:3]=rgb
        rgba[:h,:w,3]=valid.astype(np.uint8)*255
    if file_identity(path)!=identity:
        raise RasterError("Raster was modified during tile rendering.")
    output=BytesIO()
    Image.fromarray(rgba,"RGBA").save(output,format="PNG")
    return output.getvalue()

def cached_tile(path,level,x,y):
    from .store import imagery_dir
    identity=file_identity(path)
    key=sha256(json.dumps(["pyramid-v1",identity,level,x,y]).encode()).hexdigest()
    budget=int(os.getenv("GEOFATHOM_TILE_CACHE_MB","256"))*1024**2
    cache=DiskTileCache(os.getenv("GEOFATHOM_TILE_CACHE_PATH") or imagery_dir()/"tile-cache.sqlite",budget)
    data=cache.get(key,lambda:render_tile(path,level,x,y))
    if file_identity(path)!=identity:
        raise RasterError("Raster changed during tile lookup.")
    return data
