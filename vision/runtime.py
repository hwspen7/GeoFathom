"""Bounded reusable model sessions with safe leases and deterministic eviction.

ONNX sessions can hold substantial native/GPU allocations. A caller must
keep a lease throughout inference; eviction never destroys an active session.
Limits are per API process, not a cluster-wide GPU quota.
"""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from threading import BoundedSemaphore, Condition, RLock
import os
import time


@dataclass
class _Entry:
    session: object
    users: int = 0
    reserved_bytes: int = 0


def _limit(name, default, minimum, maximum):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (ValueError, TypeError) as error:
        raise ValueError(name + " must be a decimal integer.") from error
    if not minimum <= value <= maximum:
        raise ValueError(name + " is outside the supported resource range.")
    return value


class ModelSessionPool:
    def __init__(self, max_cached=2, max_parallel=2, max_reserved_bytes=None):
        if (type(max_cached) is not int or type(max_parallel) is not int
                or not 1 <= max_cached <= 8 or not 1 <= max_parallel <= 8):
            raise ValueError("Invalid model pool capacity.")
        if max_reserved_bytes is not None and (type(max_reserved_bytes) is not int or max_reserved_bytes<1):
            raise ValueError('Invalid model reservation budget.')
        self._budget=max_reserved_bytes
        self._active_bytes=0
        self.max_cached = max_cached
        self.max_parallel = max_parallel
        self._permits = BoundedSemaphore(max_parallel)
        self._condition = Condition(RLock())
        self._sessions = OrderedDict()

    @contextmanager
    def lease(self, key, factory, timeout=30., *, reserved_bytes=0, working_bytes=0):
        """Reserve model and per-call tensor bytes before constructing a session.

        Evict only idle models. The reservation is deliberately conservative
        bookkeeping, not measurement of third-party runtime allocations.
        """
        if not isinstance(timeout,(int,float)) or not 0<timeout<=120:
            raise ValueError("Model acquisition timeout must be 0–120 seconds.")
        if any(type(n) is not int or n<0 for n in (reserved_bytes,working_bytes)):
            raise ValueError("Invalid model memory reservation.")
        if self._budget is not None and reserved_bytes+working_bytes>self._budget:
            raise MemoryError("Model reservation exceeds total device budget.")
        deadline=time.monotonic()+timeout
        if not self._permits.acquire(timeout=timeout):
            raise RuntimeError("Vision inference concurrency limit is busy.")
        entry=None
        try:
            with self._condition:
                while entry is None:
                    existing=self._sessions.get(key)
                    if existing is not None and existing.reserved_bytes!=reserved_bytes:
                        raise ValueError("Cached model reservation cannot change.")
                    extra=0 if existing is not None else reserved_bytes
                    def overloaded():
                        count_full=existing is None and len(self._sessions)>=self.max_cached
                        memory_full=(self._budget is not None and
                            sum(v.reserved_bytes for v in self._sessions.values())+
                            self._active_bytes+working_bytes+extra>self._budget)
                        return count_full or memory_full
                    while overloaded():
                        victim=next((name for name,v in self._sessions.items()
                                    if name!=key and v.users==0),None)
                        if victim is None:break
                        del self._sessions[victim]
                    if overloaded():
                        remaining=deadline-time.monotonic()
                        if remaining<=0:
                            raise RuntimeError("No idle vision model capacity is available.")
                        self._condition.wait(timeout=remaining)
                        continue
                    if existing is None:
                        # Serialization prevents duplicate device allocations.
                        entry=_Entry(factory(),0,reserved_bytes)
                        self._sessions[key]=entry
                    else:
                        entry=existing
                    entry.users+=1
                    self._active_bytes+=working_bytes
                    self._sessions.move_to_end(key)
            try:
                yield entry.session
            finally:
                with self._condition:
                    entry.users-=1
                    self._active_bytes-=working_bytes
                    self._condition.notify_all()
        finally:
            self._permits.release()

    def reservations(self):
        with self._condition:
            return {"cached_bytes":sum(v.reserved_bytes for v in self._sessions.values()),
                    "active_working_bytes":self._active_bytes,"budget_bytes":self._budget}

    def snapshot(self):
        """Expose only non-sensitive resource counters, never model file paths."""
        with self._condition:
            return {"cached_sessions": len(self._sessions),
                    "leased_sessions": sum(v.users for v in self._sessions.values()),
                    "max_cached": self.max_cached,
                    "max_parallel": self.max_parallel}


@lru_cache(maxsize=16)
def _pooled(device, max_cached, max_parallel, budget):
    return ModelSessionPool(max_cached,max_parallel,budget)


def pool_for(device):
    if device not in ("cpu", "cuda"):
        raise ValueError("Vision device must be cpu or cuda.")
    max_cached = _limit("GEOFATHOM_VISION_MAX_CACHED_MODELS", 2, 1, 8)
    max_parallel = _limit(
        "GEOFATHOM_VISION_PARALLEL_INFERENCE",
        1 if device == "cuda" else 2, 1, 8)
    budget=_limit('GEOFATHOM_VISION_'+('GPU' if device=='cuda' else 'CPU')+'_TOTAL_MB',
                  8192 if device=='cuda' else 4096,256,65536)*1024**2
    return _pooled(device,max_cached,max_parallel,budget)


def tensor_budget_mb():
    return _limit("GEOFATHOM_VISION_TENSOR_MEMORY_MB", 128, 8, 1024)


def gpu_arena_budget_mb():
    return _limit("GEOFATHOM_VISION_GPU_ARENA_MB", 2048, 128, 32768)


def cpu_threads():
    return _limit("GEOFATHOM_VISION_CPU_THREADS", 2, 1, 16)
