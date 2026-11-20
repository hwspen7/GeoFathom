"""End-to-end GeoTIFF -> click -> pixel mask -> GeoJSON -> area tests."""

from pathlib import Path

import os

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from core.main import app
from geometry.mask import seeded_region
from geometry.measure import measure_geometry
from imagery.raster import metadata, preview_png
from vision.trace import trace_raster

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_imagery(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "test-imagery-admin")


@pytest.fixture
def geotiff(tmp_path):
    path = tmp_path / "colored-roof.tif"
    rgb = np.zeros((3, 64, 64), dtype=np.uint8)
    rgb[:] = 8
    rgb[0, 16:32, 20:36] = 170
    rgb[1, 16:32, 20:36] = 90
    rgb[2, 16:32, 20:36] = 55
    transform = from_origin(120.0, 32.0, 0.00001, 0.00001)
    with rasterio.open(
        path, "w", driver="GTiff", width=64, height=64,
        count=3, dtype="uint8", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(rgb)
    return path


def test_raster_metadata_and_png(geotiff):
    item = metadata(geotiff)
    assert item["crs"] == "EPSG:4326"
    assert item["corners"][0] == [120.0, 32.0]
    assert item["bands"] == 3
    assert preview_png(geotiff).startswith(b"\x89PNG")


def test_click_to_geojson_and_geodesic_area(geotiff):
    with rasterio.open(geotiff) as src:
        x, y = src.transform * (25.5, 23.5)
    result = trace_raster(geotiff, "local-test", x, y, "color", 8, 64)
    assert result["provider"] == "color"
    assert result["pixel_count"] == 256
    assert result["geometry"]["type"] == "Polygon"
    assert result["geometry_crs"] == "EPSG:4326"
    assert result["window_truncated"] is False
    assert result["measurement"]["area_m2"] > 200
    assert measure_geometry(result["geometry"])["area_m2"] == pytest.approx(
        result["measurement"]["area_m2"]
    )


def test_python_and_cpp_segmentation_match():
    rgb = np.zeros((32, 32, 3), dtype=np.uint8)
    rgb[8:16, 9:20, :] = [180, 80, 40]
    from geometry import mask
    expected = mask._python_region(rgb, 12, 11, 10)
    observed, engine = seeded_region(rgb, 12, 11, 10)
    assert np.array_equal(observed, expected)
    assert engine in {"cpp-seeded-region", "python-seeded-region"}
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE") == "1":
        assert engine == "cpp-seeded-region"


def test_image_upload_and_map_preview(geotiff):
    no_key = client.post(
        "/imagery/upload", files={"file": ("source.tif", geotiff.read_bytes(), "image/tiff")},
    )
    assert no_key.status_code == 403
    imported = client.post(
        "/imagery/upload",
        files={"file": ("sample.tif", geotiff.read_bytes(), "image/tiff")},
        headers={"X-GeoFathom-Admin-Token": "test-imagery-admin"},
    )
    assert imported.status_code == 201, imported.text
    image = imported.json()
    assert image["name"] == "sample.tif"
    assert image["preview_url"].endswith("/preview")
    assert len(image["corners"]) == 4
    assert client.get("/imagery").json()["count"] == 1
    assert client.get(image["preview_url"]).content.startswith(b"\x89PNG")
    traced = client.post("/vision/trace", json={
        "image_id": image["id"], "longitude": 120.00025,
        "latitude": 31.99977, "method": "color",
        "tolerance": 8, "window_size": 64,
    })
    assert traced.status_code == 200, traced.text
    assert traced.json()["pixel_count"] == 256
    assert traced.json()["measurement"]["area_m2"] > 200
    project = client.post("/projects", json={"name": "Image outlines"}).json()
    saved = client.post(f"/projects/{project['id']}/features", json={
        "name": "Image-derived region",
        "geometry": traced.json()["geometry"],
        "source": traced.json()["source"],
        "properties": {
            "source_type": "image_derived",
            "image_id": image["id"],
            "trace_engine": traced.json()["engine"],
            "quality": "requires_user_review",
        },
    })
    assert saved.status_code == 201, saved.text
    exported = client.get(f"/projects/{project['id']}/export").json()
    props = exported["features"][0]["properties"]
    assert props["image_id"] == image["id"]
    assert props["quality"] == "requires_user_review"


def test_explicit_sam_unavailable_and_invalid_raster(geotiff, tmp_path):
    imported = client.post(
        "/imagery/upload",
        files={"file": ("sample.tif", geotiff.read_bytes(), "image/tiff")},
        headers={"X-GeoFathom-Admin-Token": "test-imagery-admin"},
    ).json()
    assert client.post("/vision/trace", json={
        "image_id": imported["id"], "longitude": 120.00025,
        "latitude": 31.99977, "method": "sam2",
    }).status_code == 501
    outside = client.post("/vision/trace", json={
        "image_id": imported["id"], "longitude": -80,
        "latitude": 40, "method": "color",
    })
    assert outside.status_code == 422
    assert client.get("/imagery/not-a-valid-id").status_code == 422
    invalid = client.post(
        "/imagery/upload", files={"file": ("bad.tif", b"not a TIFF", "image/tiff")},
        headers={"X-GeoFathom-Admin-Token": "test-imagery-admin"},
    )
    assert invalid.status_code == 422
    assert client.get("/imagery").json()["count"] == 1


def test_raster_without_crs_rejected(tmp_path):
    path = tmp_path / "unreferenced.tif"
    with rasterio.open(path, "w", driver="GTiff", width=10, height=10,
                       count=1, dtype="uint8") as dst:
        dst.write(np.ones((1, 10, 10), dtype=np.uint8))
    from imagery.raster import RasterError
    with pytest.raises(RasterError):
        metadata(path)



def test_projected_crs_is_transformed_before_geodesic_area(tmp_path):
    from rasterio.warp import transform

    path = tmp_path / "projected.tif"
    raster = np.zeros((3, 64, 64), dtype=np.uint8)
    raster[:, 12:36, 12:36] = np.array([190, 110, 62], dtype=np.uint8)[:, None, None]
    affine = from_origin(13_400_000, 3_800_000, 2, 2)
    with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=3,
                       dtype="uint8", crs="EPSG:3857", transform=affine) as dst:
        dst.write(raster)
    x, y = affine @ (24.5, 24.5)
    lons, lats = transform("EPSG:3857", "EPSG:4326", [x], [y])
    result = trace_raster(path, "projected", lons[0], lats[0], "color", 8, 64)
    assert result["pixel_count"] == 24 * 24
    assert result["source_crs"] == "EPSG:3857"
    assert result["geometry_crs"] == "EPSG:4326"
    assert result["measurement"]["area_m2"] > 1000
