"""Native C++ seeded RGB region growing, with a deterministic Python fallback."""

import ctypes
from collections import deque

import numpy as np

from .topology import _native


def _python_region(image: np.ndarray, seed_x: int, seed_y: int, tolerance: int) -> np.ndarray:
    height, width, _ = image.shape
    reference = image[seed_y, seed_x].astype(np.int16)
    matching = np.max(np.abs(image.astype(np.int16) - reference), axis=2) <= tolerance
    output = np.zeros((height, width), dtype=np.uint8)
    queue = deque([(seed_y, seed_x)])
    output[seed_y, seed_x] = 1
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y, x - 1), (y, x + 1), (y - 1, x), (y + 1, x)):
            if (
                0 <= nx < width and 0 <= ny < height
                and not output[ny, nx] and matching[ny, nx]
            ):
                output[ny, nx] = 1
                queue.append((ny, nx))
    return output


def seeded_region(
    image: np.ndarray, seed_x: int, seed_y: int, tolerance: int = 20,
) -> tuple[np.ndarray, str]:
    """Return one 4-connected seed-color mask and the executed engine name."""
    if (
        not isinstance(image, np.ndarray) or image.ndim != 3
        or image.shape[2] != 3 or image.dtype != np.uint8
        or not (1 <= image.shape[0] <= 1024 and 1 <= image.shape[1] <= 1024)
        or not (0 <= seed_x < image.shape[1] and 0 <= seed_y < image.shape[0])
        or not (0 <= tolerance <= 255)
    ):
        raise ValueError("Expected a 1–1024 pixel RGB uint8 image, valid seed and tolerance.")
    pixels = np.ascontiguousarray(image)
    library = _native()
    if library is not None and hasattr(library, "gf_seeded_rgb_region"):
        fn = library.gf_seeded_rgb_region
        fn.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
        ]
        fn.restype = ctypes.c_int
        output = np.zeros(pixels.shape[:2], dtype=np.uint8)
        count = fn(
            pixels.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            pixels.shape[1], pixels.shape[0], seed_x, seed_y, tolerance,
            output.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        )
        if count >= 0:
            return output, "cpp-seeded-region"
    return _python_region(pixels, seed_x, seed_y, tolerance), "python-seeded-region"
