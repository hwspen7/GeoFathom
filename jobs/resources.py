"""Optional process-level CPU affinity and virtual address-space limits."""
import os

def configure_child(slot=0):
    """Apply only explicitly configured constraints; reject impossible requests.

    Affinity is available through psutil on Linux/Windows. Linux RLIMIT_AS
    constrains VIRTUAL address space, not RSS. CUDA can reserve large
    address ranges, so this opt-in limit is for CPU-only computation.
    """
    cores=int(os.getenv("GEOFATHOM_CPU_CORES_PER_WORKER","0"))
    if not 0<=cores<=64:
        raise ValueError("CPU cores per worker must be 0–64.")
    if cores:
        import psutil
        process=psutil.Process()
        if not hasattr(process,"cpu_affinity"):
            raise RuntimeError("CPU affinity is unsupported on this platform.")
        available=sorted(process.cpu_affinity())
        start=slot*cores
        selected=available[start:start+cores]
        if len(selected)!=cores:
            raise RuntimeError("Not enough distinct CPU cores for this worker slot.")
        process.cpu_affinity(selected)
        os.environ["GEOFATHOM_NATIVE_THREADS"]=str(min(8,cores))
        os.environ["GEOFATHOM_VISION_CPU_THREADS"]=str(min(16,cores))
        os.environ["GDAL_NUM_THREADS"]=str(cores)
    virtual=int(os.getenv("GEOFATHOM_RASTER_AS_MB","0"))
    if virtual:
        if not 512<=virtual<=65536:
            raise ValueError("Address-space limit must be 512–65536 MiB.")
        if any(os.getenv(k,"cpu").lower()!="cpu" for k in
                ("GEOFATHOM_SPECTRAL_DEVICE","GEOFATHOM_VISION_DEVICE")):
            raise RuntimeError("Virtual address-space limit is CPU-only.")
        try:
            import resource
        except ImportError as error:
            raise RuntimeError("RLIMIT_AS is unavailable on this OS.") from error
        old_soft,old_hard=resource.getrlimit(resource.RLIMIT_AS)
        desired=virtual*1024*1024
        if old_hard!=resource.RLIM_INFINITY:
            desired=min(desired,old_hard)
        resource.setrlimit(resource.RLIMIT_AS,(desired,old_hard))
