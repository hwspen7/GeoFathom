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
    def __init__(self, max_cached=2, max_parallel=2):
        if (type(max_cached) is not int or type(max_parallel) is not int
                or not 1 <= max_cached <= 8 or not 1 <= max_parallel <= 8):
            raise ValueError("Invalid model pool capacity.")
        self.max_cached = max_cached
        self.max_parallel = max_parallel
        self._permits = BoundedSemaphore(max_parallel)
        self._condition = Condition(RLock())
        self._sessions = OrderedDict()

    @contextmanager
    def lease(self, key, factory, timeout=30.):
        """Acquire a session and hold its lifetime until inference completes.

        The semaphore bounds simultaneous model runs. The condition protects
        the LRU, prevents duplicate construction of the same model, and waits
        for idle victims rather than evicting a session under active inference.
        """
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
            raise ValueError("Model acquisition timeout must be 0–120 seconds.")
        deadline = time.monotonic() + timeout
        if not self._permits.acquire(timeout=timeout):
            raise RuntimeError("Vision inference concurrency limit is busy.")
        entry = None
        try:
            with self._condition:
                while entry is None:
                    if key in self._sessions:
                        entry = self._sessions[key]
                        entry.users += 1
                        self._sessions.move_to_end(key)
                        break
                    if len(self._sessions) >= self.max_cached:
                        victim = next((name for name, value
                                       in self._sessions.items()
                                       if value.users == 0), None)
                        if victim is not None:
                            del self._sessions[victim]
                        else:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise RuntimeError("No idle vision model session is available.")
                            self._condition.wait(timeout=remaining)
                            continue
                    # Session initialization is intentionally serialized to
                    # avoid duplicate native GPU allocations for the same key.
                    entry = _Entry(factory(), 1)
                    self._sessions[key] = entry
            try:
                yield entry.session
            finally:
                with self._condition:
                    entry.users -= 1
                    self._condition.notify_all()
        finally:
            self._permits.release()

    def snapshot(self):
        """Expose only non-sensitive resource counters, never model file paths."""
        with self._condition:
            return {"cached_sessions": len(self._sessions),
                    "leased_sessions": sum(v.users for v in self._sessions.values()),
                    "max_cached": self.max_cached,
                    "max_parallel": self.max_parallel}


@lru_cache(maxsize=16)
def _pooled(device, max_cached, max_parallel):
    return ModelSessionPool(max_cached, max_parallel)


def pool_for(device):
    if device not in ("cpu", "cuda"):
        raise ValueError("Vision device must be cpu or cuda.")
    max_cached = _limit("GEOFATHOM_VISION_MAX_CACHED_MODELS", 2, 1, 8)
    max_parallel = _limit(
        "GEOFATHOM_VISION_PARALLEL_INFERENCE",
        1 if device == "cuda" else 2, 1, 8)
    return _pooled(device, max_cached, max_parallel)


def tensor_budget_mb():
    return _limit("GEOFATHOM_VISION_TENSOR_MEMORY_MB", 128, 8, 1024)


def gpu_arena_budget_mb():
    return _limit("GEOFATHOM_VISION_GPU_ARENA_MB", 2048, 128, 32768)


def cpu_threads():
    return _limit("GEOFATHOM_VISION_CPU_THREADS", 2, 1, 16)
