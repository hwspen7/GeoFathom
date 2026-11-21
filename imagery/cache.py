"""Process-local byte-budgeted LRU for immutable rendered raster products."""
from collections import OrderedDict
from threading import RLock
import os
from pathlib import Path

class ByteCache:
    def __init__(self,limit):
        if type(limit) is not int or limit<0:
            raise ValueError("Cache budget must be nonnegative.")
        self.limit=limit
        self._items=OrderedDict()
        self._size=0
        self._lock=RLock()
        self._hits=0
        self._misses=0

    def get(self,key,load):
        with self._lock:
            if key in self._items:
                self._hits+=1
                self._items.move_to_end(key)
                return self._items[key]
            self._misses+=1
        data=load()
        if not isinstance(data,bytes):
            raise TypeError("Raster cache stores immutable bytes only.")
        if len(data)>self.limit or not data:
            return data
        with self._lock:
            previous=self._items.pop(key,None)
            if previous is not None:
                self._size-=len(previous)
            while self._items and self._size+len(data)>self.limit:
                _,value=self._items.popitem(last=False)
                self._size-=len(value)
            self._items[key]=data
            self._size+=len(data)
        return data

    def stats(self):
        with self._lock:
            return {"entries":len(self._items),"bytes":self._size,
                    "limit":self.limit,"hits":self._hits,"misses":self._misses}

def file_identity(path):
    p=Path(path).resolve()
    s=p.stat()
    return str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

from functools import lru_cache

@lru_cache(maxsize=1)
def preview_cache():
    mb=int(os.getenv("GEOFATHOM_PREVIEW_CACHE_MB","64"))
    if not 0<=mb<=512:
        raise ValueError("Preview cache must be 0–512 MiB.")
    return ByteCache(mb*1024*1024)

def cached_preview(path):
    from .raster import preview_png
    key=file_identity(path)
    def load():
        png=preview_png(path)
        if file_identity(path)!=key:
            raise RuntimeError("Imagery changed while rendering a preview.")
        return png
    return preview_cache().get(("preview-v1",key),load)
