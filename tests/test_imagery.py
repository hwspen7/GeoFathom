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
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH", str(tmp_path / "projects.sqlite"))
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
    import hashlib
    assert image["sha256"]==hashlib.sha256(geotiff.read_bytes()).hexdigest()
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


def test_local_cog_import_preserves_overviews_and_source_checksum(tmp_path,monkeypatch):
    from imagery.cli import import_local_image
    from imagery.store import image_file
    import hashlib
    source=tmp_path/"source-cog.tif"
    with rasterio.open(
        source,"w",driver="GTiff",width=256,height=256,count=4,
        dtype="uint8",crs="EPSG:4326",
        transform=from_origin(20,30,.00001,.00001),
        tiled=True,blockxsize=128,blockysize=128,compress="deflate",
    ) as dataset:
        dataset.write(np.full((4,256,256),99,dtype=np.uint8))
        dataset.build_overviews([2,4],rasterio.enums.Resampling.average)
    item=import_local_image(source,"Source COG")
    assert item["name"]=="Source COG"
    assert item["is_tiled"] is True
    assert item["block_shapes"][0]==[128,128]
    assert item["overviews"]==[2,4]
    assert item["sha256"]==hashlib.sha256(source.read_bytes()).hexdigest()
    assert image_file(item["id"]).read_bytes()==source.read_bytes()
    assert metadata(source)["block_shapes"][0]==[128,128]
    with pytest.raises(Exception,match="already inside"):
        import_local_image(image_file(item["id"]))


def test_local_desktop_import_needs_explicit_header_and_trusted_origin(geotiff, monkeypatch):
    monkeypatch.delenv("GEOFATHOM_MODEL_ADMIN_TOKEN")
    monkeypatch.delenv("GEOFATHOM_LOCAL_RASTER_IMPORT", raising=False)
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE", "local")
    monkeypatch.setenv("GEOFATHOM_CORS_ORIGINS", "http://127.0.0.1:5173")
    files={"file":("local.tif",geotiff.read_bytes(),"image/tiff")}
    assert client.post("/imagery/upload",files=files).status_code==403
    assert client.post("/imagery/upload",files=files,headers={
        "X-GeoFathom-Local-Import":"1","Origin":"https://untrusted.example"}).status_code==403
    accepted=client.post("/imagery/upload",files=files,headers={
        "X-GeoFathom-Local-Import":"1","Origin":"http://127.0.0.1:5173"})
    assert accepted.status_code==201,accepted.text
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN","protected")
    assert client.post("/imagery/upload",files=files,headers={
        "X-GeoFathom-Local-Import":"1"}).status_code==403


def test_float_dem_preview_is_transparent_where_nodata_or_nan(tmp_path):
    from io import BytesIO
    from PIL import Image
    path=tmp_path/"partially-missing.tif"
    values=np.full((32,32),-9999.,dtype=np.float32)
    values[20:,0:16]=120.
    values[20:,16:]=200.
    values[25,18]=np.nan
    with rasterio.open(path,"w",driver="GTiff",count=1,width=32,height=32,
                       dtype="float32",crs="EPSG:32617",
                       transform=from_origin(500000,4500000,10,10),
                       nodata=-9999) as dst:
        dst.write(values,1)
    rendered=np.array(Image.open(BytesIO(preview_png(path))).convert("RGBA"))
    assert rendered[0,0,3]==0
    assert rendered[25,18,3]==0
    assert rendered[22,4,3]==255 and rendered[22,20,3]==255
    # More than half of the source is NoData, yet the valid terrain still
    # retains full contrast instead of stretching around -9999 meters.
    assert int(rendered[22,20,0])-int(rendered[22,4,0])>200


def test_raster_source_metadata_keeps_native_units_and_declared_datum(tmp_path):
    path=tmp_path/"source-metadata.tif"
    with rasterio.open(path,"w",driver="GTiff",width=8,height=8,
                       count=1,dtype="float32",crs="EPSG:32617",
                       transform=from_origin(500000,4500000,5,5)) as ds:
        ds.write(np.ones((8,8),dtype=np.float32),1)
        ds.update_tags(VERTICAL_UNIT="meter",VERTICAL_DATUM="NAVD88")
    result=metadata(path)
    assert result["resolution"]==[5.,5.]
    assert result["resolution_unit"] in {"metre","meter"}
    assert result["vertical_unit"]=="meter"
    assert result["vertical_datum"]=="NAVD88"
    assert result["acquired_at"] is None
    with rasterio.open(path,"r+") as ds:
        ds.update_tags(VERTICAL_DATUM="")
    assert metadata(path)["vertical_datum"] is None


def test_desktop_raster_opt_in_preserves_model_and_deployment_auth(geotiff, monkeypatch):
    from core.security import local_raster_import_enabled
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE", "local")
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "protected")
    monkeypatch.setenv("GEOFATHOM_LOCAL_RASTER_IMPORT", "1")
    headers = {"X-GeoFathom-Local-Import": "1", "Origin": "http://127.0.0.1:5173"}
    files = {"file": ("desktop.tif", geotiff.read_bytes(), "image/tiff")}
    assert client.get("/capabilities").json()["local_raster_import"] is True
    assert client.post("/imagery/upload", files=files, headers=headers).status_code == 201
    assert client.post("/imagery/upload", files=files).status_code == 403
    assert client.post("/imagery/upload", files=files, headers={
        **headers, "Origin": "https://untrusted.example"
    }).status_code == 403
    from intelligence.catalog import require_admin
    with pytest.raises(PermissionError):
        require_admin(None)
    monkeypatch.setenv("GEOFATHOM_LOCAL_RASTER_IMPORT", "0")
    assert client.get("/capabilities").json()["local_raster_import"] is False
    assert client.post("/imagery/upload", files=files, headers=headers).status_code == 403
    monkeypatch.setenv("GEOFATHOM_LOCAL_RASTER_IMPORT", "1")
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE", "required")
    assert not local_raster_import_enabled()
    monkeypatch.setenv("GEOFATHOM_API_TOKEN", "x" * 32)
    assert client.post("/imagery/upload", files=files, headers={
        **headers, "X-GeoFathom-API-Key": "x" * 32
    }).status_code == 403
