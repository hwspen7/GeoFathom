"""Optional OS-enforced aggregate memory boundary for compute children.

Linux uses an operator-provisioned, delegated cgroup v2. Windows uses a
named Job Object with a combined committed-memory limit, shared by workers
on the same host and in the same session. No sampled RSS approximation is
used as a substitute when this hard boundary is explicitly requested.
"""
import os
from pathlib import Path
import hashlib
import sys

_Windows_job=None

def requested_budget():
    mb=int(os.getenv("GEOFATHOM_WORKER_MEMORY_MB","0"))
    if mb and not 128<=mb<=65536:
        raise ValueError("Aggregate worker memory must be 128–65536 MiB.")
    return mb*1024**2

def _linux_join(limit):
    root=Path("/sys/fs/cgroup").resolve()
    configured=os.getenv("GEOFATHOM_WORKER_CGROUP")
    if not configured:
        raise RuntimeError("Hard memory limit requires a provisioned cgroup v2.")
    group=Path(configured).resolve(strict=True)
    if root not in group.parents:
        raise RuntimeError("Worker cgroup must be below /sys/fs/cgroup.")
    raw=(group/"memory.max").read_text().strip()
    if raw=="max" or not 0<int(raw)<=limit:
        raise RuntimeError("Worker cgroup memory.max exceeds the requested hard limit.")
    (group/"cgroup.procs").write_text(str(os.getpid()))
    if str(os.getpid()) not in (group/"cgroup.procs").read_text().split():
        raise RuntimeError("Worker was not attached to the memory cgroup.")
    return int(raw)

def _windows_join(limit,namespace):
    import ctypes
    from ctypes import wintypes as w
    global _Windows_job
    k=ctypes.WinDLL("kernel32",use_last_error=True)
    size=ctypes.c_size_t
    class Basic(ctypes.Structure):
        _fields_=[("PerProcessUserTimeLimit",ctypes.c_longlong),
                   ("PerJobUserTimeLimit",ctypes.c_longlong),("LimitFlags",w.DWORD),
                   ("MinimumWorkingSetSize",size),("MaximumWorkingSetSize",size),
                   ("ActiveProcessLimit",w.DWORD),("Affinity",size),
                   ("PriorityClass",w.DWORD),("SchedulingClass",w.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in
                  ("ReadOperationCount","WriteOperationCount","OtherOperationCount",
                   "ReadTransferCount","WriteTransferCount","OtherTransferCount")]
    class Extended(ctypes.Structure):
        _fields_=[("BasicLimitInformation",Basic),("IoInfo",IO),
                   ("ProcessMemoryLimit",size),("JobMemoryLimit",size),
                   ("PeakProcessMemoryUsed",size),("PeakJobMemoryUsed",size)]
    signatures={
        "CreateMutexW":([ctypes.c_void_p,w.BOOL,w.LPCWSTR],w.HANDLE),
        "WaitForSingleObject":([w.HANDLE,w.DWORD],w.DWORD),
        "ReleaseMutex":([w.HANDLE],w.BOOL),
        "CreateJobObjectW":([ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
        "QueryInformationJobObject":([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p],w.BOOL),
        "SetInformationJobObject":([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
        "GetCurrentProcess":([],w.HANDLE),
        "AssignProcessToJobObject":([w.HANDLE,w.HANDLE],w.BOOL),
        "IsProcessInJob":([w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL),
        "CloseHandle":([w.HANDLE],w.BOOL),
    }
    for name,(args,result) in signatures.items():
        func=getattr(k,name);func.argtypes=args;func.restype=result
    def checked(value):
        if not value:raise ctypes.WinError(ctypes.get_last_error())
        return value
    name="Local\\GeoFathomMemory-"+hashlib.sha256(namespace.encode()).hexdigest()[:32]
    mutex=checked(k.CreateMutexW(None,False,name+"-setup"))
    handle=None
    acquired=False
    try:
        status=k.WaitForSingleObject(mutex,30000)
        if status not in (0,128):
            raise RuntimeError("Timed out configuring shared Windows memory Job Object.")
        acquired=True
        ctypes.set_last_error(0)
        handle=checked(k.CreateJobObjectW(None,name))
        existing=ctypes.get_last_error()==183
        info=Extended()
        flag=0x200 # JOB_OBJECT_LIMIT_JOB_MEMORY, combined commit budget
        if existing:
            checked(k.QueryInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info),None))
            if not (info.BasicLimitInformation.LimitFlags&flag) or info.JobMemoryLimit!=limit:
                raise RuntimeError("Shared Windows worker memory budget differs.")
        else:
            info.BasicLimitInformation.LimitFlags=flag
            info.JobMemoryLimit=limit
            checked(k.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)))
        process=k.GetCurrentProcess()
        member=w.BOOL()
        checked(k.IsProcessInJob(process,handle,ctypes.byref(member)))
        if not member.value:checked(k.AssignProcessToJobObject(handle,process))
        # Keep the named object alive for the duration of this interpreter.
        if _Windows_job:k.CloseHandle(_Windows_job)
        _Windows_job=handle;handle=None
        return int(info.JobMemoryLimit)
    finally:
        if handle:k.CloseHandle(handle)
        if acquired:k.ReleaseMutex(mutex)
        k.CloseHandle(mutex)

def enforce(namespace):
    limit=requested_budget()
    if not limit:return None
    if sys.platform.startswith("linux"):
        return {"mechanism":"cgroup-v2","limit_bytes":_linux_join(limit)}
    if os.name=="nt":
        group=os.getenv("GEOFATHOM_WORKER_MEMORY_GROUP",namespace)
        return {"mechanism":"windows-job-memory","limit_bytes":_windows_join(limit,group)}
    raise RuntimeError("Requested aggregate hard memory policy is unsupported on this OS.")
