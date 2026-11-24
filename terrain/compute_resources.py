"""Host-aware terrain resource admission and reproducible per-task budgets.

The process-local admission gate is intentionally conservative. It does not
claim to be an OS memory boundary or a distributed scheduler. Full-grid
algorithms retain explicit engineering ceilings until independently validated
out-of-core implementations exist.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import shutil
from threading import RLock
from uuid import uuid4

import psutil
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

MiB = 1024**2
GiB = 1024**3
CEILINGS = {"slope": 256_000_000, "surface": 32_000_000,
            "global": 8_000_000, "visibility": 1_048_576, "least_cost": 2_097_152}
# Conservative admission estimates, not measured peak RSS guarantees.
CELL_BYTES = {"surface": 512, "global": 1024, "visibility": 768, "least_cost": 1024}
LOCAL_OPERATIONS = frozenset({"dem_difference", "elevation", "slope_map", "aspect_map",
    "hillshade", "tri", "tpi", "curvature", "plan_curvature", "profile_curvature",
    "cutfill_map", "suitability", "volume", "distribution"})


class ComputePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    mode: Literal["automatic", "manual"] = "automatic"
    memory_percent: int = Field(default=65, ge=10, le=85)
    concurrent_tasks: int = Field(default=1, ge=1, le=4)
    tile_size: Literal[128, 256, 512, 1024] = 512
    slope_cells: int = Field(default=256_000_000, ge=9, le=256_000_000)
    surface_cells: int = Field(default=32_000_000, ge=9, le=32_000_000)
    global_cells: int = Field(default=8_000_000, ge=9, le=8_000_000)
    visibility_cells: int = Field(default=1_048_576, ge=9, le=1_048_576)
    least_cost_cells: int = Field(default=2_097_152, ge=9, le=2_097_152)
    viewshed_distance_m: int = Field(default=10000, ge=100, le=100000)
    ray_samples: int = Field(default=100_000_000, ge=1000, le=500_000_000)


@dataclass(frozen=True)
class Host:
    total_bytes: int
    available_bytes: int
    logical_cpus: int
    scratch_free_bytes: int


@dataclass(frozen=True)
class Limits:
    memory_bytes: int
    concurrent_tasks: int
    tile_size: int
    slope_cells: int
    surface_cells: int
    global_cells: int
    visibility_cells: int
    least_cost_cells: int
    viewshed_distance_m: int
    ray_samples: int
    native_slope_cells: int

    def grid(self, operation):
        group = ("surface" if operation in LOCAL_OPERATIONS else
                 "visibility" if operation in {"visibility", "viewshed_multi"} else
                 "least_cost" if operation == "least_cost" else "global")
        cells = getattr(self, group + "_cells")
        # Do not arbitrarily reject narrow grids at sqrt(cell budget).
        side = min({"surface": 8192, "global": 4096, "visibility": 2048,
                    "least_cost": 4096}[group], max(2, cells))
        return side, cells


# Direct library calls retain the established reference contract unless an
# explicit task context is supplied. API calls always take a host snapshot.
_REFERENCE = Limits(2*GiB, 1, 512, 32_000_000, 8_000_000, 1_000_000,
                    262_144, 262_144, 10000, 100_000_000, 8_000_000)
_active: ContextVar[Limits | None] = ContextVar("terrain_compute_limits", default=None)
_lock = RLock()
_running = 0


class ResourceBusy(RuntimeError):
    pass


def _settings_path():
    from storage.database import database_path
    path = database_path()
    return path.with_name(path.name + ".terrain-compute.json")


def load_policy():
    path = _settings_path()
    try:
        return ComputePolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ComputePolicy()


def save_policy(policy):
    with _lock:
        if _running:
            raise ResourceBusy("Finish or cancel active terrain tasks before changing resource settings.")
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        try:
            temporary.write_text(policy.model_dump_json(), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _cgroup_memory(total, available, root=Path("/sys/fs/cgroup")):
    # Respect every ancestor of the current cgroup, not only the host total.
    try:
        lines = Path("/proc/self/cgroup").read_text().splitlines()
        relative = next(line.split(":", 2)[2] for line in lines if line.startswith("0::"))
        directory = (root / relative.lstrip("/")).resolve()
        root = root.resolve()
        if directory != root and root not in directory.parents:
            return total, available
        for group in (directory, *directory.parents):
            if group != root and root not in group.parents:
                break
            try:
                maximum = (group / "memory.max").read_text().strip()
                if maximum != "max":
                    limit = int(maximum)
                    used = int((group / "memory.current").read_text())
                    total = min(total, limit)
                    available = min(available, max(0, limit-used))
            except (OSError, ValueError):
                continue
    except (OSError, ValueError, StopIteration):
        pass
    return total, available


def detect_host():
    memory = psutil.virtual_memory()
    total, available = _cgroup_memory(int(memory.total), int(memory.available))
    try:
        cpus = len(psutil.Process().cpu_affinity())
    except (AttributeError, OSError, psutil.Error):
        cpus = os.cpu_count() or 1
    path = _settings_path().parent
    while not path.exists() and path != path.parent:
        path = path.parent
    return Host(total, available, max(1, cpus), int(shutil.disk_usage(path).free))


def resolve_limits(policy, host):
    manual = policy.mode == "manual"
    concurrency = min(host.logical_cpus, policy.concurrent_tasks if manual else 1)
    concurrency = max(1, concurrency)
    percent = policy.memory_percent if manual else 65
    # Reserve host headroom and divide the aggregate budget among admitted tasks.
    aggregate = min(host.total_bytes*percent//100, host.available_bytes*3//4,
                    64*GiB)
    budget = max(0, aggregate//concurrency)
    # At least 128 MiB is required for the API, GDAL and minimum tile working set.
    usable = max(0, budget-128*MiB)
    tile_ceiling = math.isqrt(usable//256) - 2
    desired = policy.tile_size if manual else (1024 if usable>=2*GiB else 512)
    tile = max((size for size in (128,256,512,1024)
                if size<=desired and size<=tile_ceiling), default=0)
    caps = {}
    for group, maximum in CEILINGS.items():
        requested = getattr(policy, group+"_cells") if manual else maximum
        if group == "slope":
            # Streaming slope is a work budget, not a whole-array allocation.
            work = max(0, min(maximum, (usable//MiB)*100_000)) if tile else 0
        else:
            work = usable//CELL_BYTES[group] if tile else 0
        caps[group+"_cells"] = min(maximum, requested, work)
    distance = policy.viewshed_distance_m if manual else min(100000, max(10000, 10000*(usable//GiB)))
    rays = policy.ray_samples if manual else min(500_000_000, max(100_000_000, 25_000_000*host.logical_cpus))
    return Limits(budget, concurrency, tile, **caps, viewshed_distance_m=distance,
                  ray_samples=rays, native_slope_cells=min(8_000_000, usable//128))


def current_limits():
    return _active.get() or _REFERENCE


def active_limits():
    return _active.get()


@contextmanager
def task_resources():
    global _running
    with _lock:
        limits = resolve_limits(load_policy(), detect_host())
        if not limits.tile_size:
            raise ResourceBusy("Insufficient available terrain memory. Free memory or reduce concurrent tasks.")
        if _running >= limits.concurrent_tasks:
            raise ResourceBusy("Terrain compute capacity is busy. Finish or cancel an active task.")
        _running += 1
    token = _active.set(limits)
    try:
        yield limits
    finally:
        _active.reset(token)
        with _lock:
            _running -= 1


def resource_status():
    with _lock:
        policy = load_policy()
        host = detect_host()
        limits = resolve_limits(policy, host)
        return {"policy": policy.model_dump(), "hardware": asdict(host),
                "effective": asdict(limits), "active_tasks": _running,
                "scope": "local_backend_process",
                "terrain_gpu": "not_available",
                "memory_protection": "estimated_admission_not_os_enforcement"}
