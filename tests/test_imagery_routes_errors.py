"""HTTP acceptance for the previously uncovered image service failure branches."""
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from core.main import app
from imagery import routes
from imagery.raster import RasterError

client=TestClient(app)


@pytest.fixture(autouse=True)
def configured(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(tmp_path/"imagery"))
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"imagery.sqlite"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN","test-route-admin")

TOKEN={"X-GeoFathom-Admin-Token":"test-route-admin"}


@pytest.mark.parametrize("operation,error,status",[
    ("info",FileNotFoundError("missing"),404),
    ("info",RasterError("invalid"),422),
    ("preview",FileNotFoundError("missing"),404),
    ("preview",RasterError("invalid"),422),
    ("pyramid",FileNotFoundError("missing"),404),
    ("pyramid",ValueError("invalid overview"),422),
    ("tile",FileNotFoundError("missing"),404),
    ("tile",RasterError("bad level"),422),
])
def test_image_read_routes_preserve_not_found_versus_invalid_raster(
    monkeypatch,operation,error,status,
):
    from imagery import pyramid
    if operation=="info":
        monkeypatch.setattr(routes,"describe",lambda *args:(_ for _ in ()).throw(error))
        url="/imagery/test-id"
    else:
        monkeypatch.setattr(routes,"image_file",lambda *args:Path("fake.tif"))
        if operation=="preview":
            monkeypatch.setattr(routes,"cached_preview",
                lambda *args:(_ for _ in ()).throw(error))
            url="/imagery/test-id/preview"
        elif operation=="pyramid":
            monkeypatch.setattr(pyramid,"pyramid_info",
                lambda *args:(_ for _ in ()).throw(error))
            url="/imagery/test-id/pyramid"
        else:
            monkeypatch.setattr(pyramid,"cached_tile",
                lambda *args:(_ for _ in ()).throw(error))
            url="/imagery/test-id/tiles/0/0/0.png"
    response=client.get(url)
    assert response.status_code==status,response.text


def test_pyramid_and_tile_serve_bounded_private_cached_responses(monkeypatch):
    from imagery import pyramid
    monkeypatch.setattr(routes,"image_file",lambda _:Path("fake.tif"))
    monkeypatch.setattr(pyramid,"pyramid_info",
        lambda path:{"levels":[{"z":0,"width":1,"height":1}]})
    monkeypatch.setattr(pyramid,"cached_tile",
        lambda *args:b"\x89PNG\r\n\x1a\nplaceholder")
    info=client.get("/imagery/test-id/pyramid")
    assert info.status_code==200
    assert info.json()["levels"][0]["width"]==1
    tile=client.get("/imagery/test-id/tiles/0/0/0.png")
    assert tile.status_code==200
    assert tile.headers["content-type"]=="image/png"
    assert "private" in tile.headers["cache-control"]


@pytest.mark.parametrize("filename,data,limit,status",[
    ("bad.png",b"123",100,422),
    ("empty.tif",b"",100,422),
    ("big.tif",b"excess",3,413),
])
def test_import_rejects_non_dem_empty_and_excess_bytes(
    monkeypatch,filename,data,limit,status,
):
    monkeypatch.setattr(routes,"MAX_UPLOAD_BYTES",limit)
    response=client.post("/imagery/upload",
        files={"file":(filename,data,"image/tiff")},headers=TOKEN)
    assert response.status_code==status,response.text
    root=routes.imagery_dir()
    assert not list(root.glob(".import-*"))


def test_import_invalid_raster_cleans_temporary_file(monkeypatch):
    def invalid(*args,**kwargs):raise RasterError("invalid raster format")
    monkeypatch.setattr(routes,"store_upload",invalid)
    response=client.post("/imagery/upload",files={
        "file":("fake.tif",b"not-a-tiff","image/tiff")},headers=TOKEN)
    assert response.status_code==422
    assert "invalid raster format" in response.text
    assert not list(routes.imagery_dir().glob(".import-*"))


@pytest.mark.parametrize("error,status",[
    (routes.CatalogSearchError("invalid bounds"),422),
    (httpx.ConnectError("offline"),503),
    (ValueError("provider malformed"),503),
])
def test_stac_search_maps_domain_and_provider_failures(monkeypatch,error,status):
    async def failure(*args,**kwargs):raise error
    monkeypatch.setattr(routes,"search_stac",failure)
    response=client.post("/imagery/catalog/search",json={
        "bbox":[-83.1,40.,-83.,40.1],"collection":"sentinel-2-l2a"})
    assert response.status_code==status,response.text


def test_dem_fetch_translates_scientific_validation_to_422(monkeypatch):
    from terrain import routes as terrain_routes
    async def reject(*args,**kwargs):
        raise RasterError("unsupported DEM grid")
    monkeypatch.setattr(terrain_routes,"run_cancelable",reject)
    response=client.post("/imagery/dem/fetch",json={
        "bbox":[-83.1,39.9,-83.,40.],"resolution_m":30},headers=TOKEN)
    assert response.status_code==422,response.text
    assert "unsupported DEM grid" in response.text


def test_loopback_local_import_requires_header_and_safe_origin(monkeypatch):
    monkeypatch.delenv("GEOFATHOM_MODEL_ADMIN_TOKEN",raising=False)
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","local")
    monkeypatch.setattr(routes,"_loopback",lambda host:True)
    monkeypatch.setattr(routes,"store_upload",lambda path,name:{"name":name})
    allowed=client.post("/imagery/upload",files={
        "file":("local.tif",b"synthetic","image/tiff")},
        headers={"X-GeoFathom-Local-Import":"1"})
    assert allowed.status_code==201,allowed.text
    assert allowed.json()["name"]=="local.tif"
    forbidden=client.post("/imagery/upload",files={
        "file":("local.tif",b"synthetic","image/tiff")},
        headers={"X-GeoFathom-Local-Import":"1","Origin":"https://unapproved.example"})
    assert forbidden.status_code==403


def test_desktop_dem_fetch_with_model_admin_configured(monkeypatch):
    from terrain import routes as terrain_routes
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE", "local")
    monkeypatch.setenv("GEOFATHOM_LOCAL_RASTER_IMPORT", "1")
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "protected")
    calls = []

    async def fake_fetch(request, fn, bbox, resolution):
        calls.append((bbox, resolution))
        return {"requested_bbox": bbox, "resolution_m": resolution}

    monkeypatch.setattr(terrain_routes, "run_cancelable", fake_fetch)
    body = {"bbox": [120.406, 36.065, 120.427, 36.078], "resolution_m": 30}
    headers = {"X-GeoFathom-Local-Import": "1", "Origin": "http://127.0.0.1:5173"}
    response = client.post("/imagery/dem/fetch", json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["requested_bbox"] == body["bbox"]
    assert calls == [(tuple(body["bbox"]), 30)]
    forbidden = client.post("/imagery/dem/fetch", json=body, headers={
        **headers, "Origin": "https://untrusted.example"
    })
    assert forbidden.status_code == 403
    assert len(calls) == 1
