"""Cooperative cancellation at bounded terrain processing checkpoints."""

class TerrainCancelled(RuntimeError):
    """The caller disconnected before terrain computation completed."""


def checkpoint(cancel=None):
    if cancel is not None and cancel.is_set():
        raise TerrainCancelled("Terrain calculation cancelled.")
