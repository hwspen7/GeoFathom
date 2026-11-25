"""Generate reproducible, synthetic GeoTIFF test data.

The output is intentionally not an actual satellite image or real landmark.
Run: python examples/create_demo.py
"""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def make_demo(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((3, 384, 384), dtype=np.uint8)
    image[:] = np.array([42, 62, 55], dtype=np.uint8)[:, None, None]
    image[:, 60:205, 80:240] = np.array([190, 134, 94], dtype=np.uint8)[:, None, None]
    image[:, 235:340, 255:352] = np.array([60, 126, 172], dtype=np.uint8)[:, None, None]
    with rasterio.open(
        path, "w", driver="GTiff", width=384, height=384,
        count=3, dtype="uint8", crs="EPSG:4326",
        transform=from_origin(0.0, 0.005, 0.00001, 0.00001),
        compress="deflate",
    ) as out:
        out.update_tags(
            DESCRIPTION="Synthetic GeoFathom trace demonstration; not satellite imagery"
        )
        out.write(image)
    return path


if __name__ == "__main__":
    print(make_demo(Path("data") / "synthetic_trace_demo.tif"))
