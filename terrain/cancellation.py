"""Cooperative cancellation at bounded terrain processing checkpoints."""

from contextvars import ContextVar

runtime_guard = ContextVar("terrain_runtime_guard", default=None)

class TerrainCancelled(RuntimeError):
    """The caller disconnected before terrain computation completed."""


def checkpoint(cancel=None):
    if cancel is not None and cancel.is_set():
        raise TerrainCancelled("Terrain calculation cancelled.")
    guard=runtime_guard.get()
    if guard is not None:guard()
