"""Contract for future vision engines, intentionally not a fake implementation."""

from typing import Protocol


class VisionProvider(Protocol):
    async def segment(self, image_reference: str, prompt: str) -> dict: ...


class VisionUnavailable(RuntimeError):
    """An imagery source and segmentation provider must be configured."""
