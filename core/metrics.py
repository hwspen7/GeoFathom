"""Operator-only process metrics with bounded label cardinality."""
from threading import Lock
import time

_lock=Lock()
_started=time.monotonic()
_count=0
_errors=0
_latency=0.
_buckets={2:0,3:0,4:0,5:0}
def observe(status,elapsed):
    global _count,_errors,_latency
    with _lock:
        _count+=1
        _errors+=int(status>=500)
        _latency+=elapsed
        family=status//100
        if family in _buckets:_buckets[family]+=1

def snapshot():
    import psutil,shutil
    from storage.database import _connect,database_path
    from geometry.topology import native_available
    from imagery.cache import preview_cache
    with _lock:
        requests={"total":_count,"server_errors":_errors,
                  "mean_ms":round(_latency/max(1,_count),3),
                  "status_families":dict(_buckets)}
    with _connect() as c:
        jobs={}
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gis_jobs'").fetchone():
            jobs={r[0]:r[1] for r in c.execute("SELECT status,count(*) FROM gis_jobs GROUP BY status")}
    proc=psutil.Process()
    rss=proc.memory_info().rss
    free=shutil.disk_usage(database_path().parent).free
    warnings=[]
    if free<128*1024**2:warnings.append("LOW_DISK")
    if jobs.get("interrupted",0):warnings.append("INTERRUPTED_JOBS")
    return {"uptime_seconds":round(time.monotonic()-_started,2),
            "requests":requests,"jobs":jobs,"rss_bytes":rss,
            "cpu_threads":proc.num_threads(),"storage_free_bytes":free,
            "native_available":native_available(),"preview_cache":preview_cache().stats(),
            "alerts":warnings}
