"""Remote-sensing analysis and replaceable ONNX segmentation integration tests."""
import json
import time

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from core.main import app
from imagery.raster import RasterError
from vision.geoai import spectral_change, spectral_index
from vision.semantic import models, semantic_segmentation

client = TestClient(app)
TRANSFORM = from_origin(120, 32, .00001, .00001)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH", str(tmp_path / "geoai.sqlite"))
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR", str(tmp_path / "vision-models"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "test-geoai-admin")
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE", "cpu")


def raster(tmp_path, name, modified=False, origin=TRANSFORM):
    path = tmp_path / name
    image = np.full((4, 64, 64), 100, dtype=np.uint16)
    if modified:
        image[0, 16:48, 16:48] = 50
        image[3, 16:48, 16:48] = 200
    with rasterio.open(path, "w", driver="GTiff", width=64, height=64,
                       count=4, dtype="uint16", crs="EPSG:4326",
                       transform=origin) as dst:
        dst.write(image)
        dst.update_tags(ACQUISITION_DATE="2026-01-01" if not modified else "2026-11-01")
    return path


def upload(path):
    response = client.post("/imagery/upload", files={
        "file": (path.name, path.read_bytes(), "image/tiff"),
    }, headers={"X-GeoFathom-Admin-Token": "test-geoai-admin"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def complete(project, kind, payload):
    response = client.post(f"/projects/{project}/jobs",
                           json={"kind":kind,"payload":payload},
                           headers={"X-GeoFathom-Admin-Token":"test-geoai-admin"})
    assert response.status_code == 202, response.text
    uid = response.json()["id"]
    stop = time.monotonic() + 8
    while time.monotonic() < stop:
        data = client.get(f"/projects/{project}/jobs/{uid}").json()
        if data["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return data
        time.sleep(.025)
    pytest.fail("GeoAI task did not complete")


def test_ndvi_vectors_have_wgs84_measurement_and_no_fake_model_confidence(tmp_path):
    path = raster(tmp_path, "new.tif", modified=True)
    data = spectral_index(path,"new","ndvi",4,1,threshold=.3,max_side=64)
    assert data["analysis"] == "ndvi"
    assert data["provider"] == "deterministic"
    assert data["model_id"] is None
    assert data["valid_pixels"] == 4096
    assert data["classified_pixels"] == 32*32
    assert len(data["features"]) == 1
    feature = data["features"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["class_name"] == "vegetation_candidate"
    assert feature["properties"]["area_m2"] > 0
    assert feature["properties"]["quality"] == "requires_user_review"
    assert data["geometry_crs"] == "EPSG:4326"


def test_two_date_warped_change_reports_gain_and_loss_without_guessing_dates(tmp_path):
    old = raster(tmp_path,"old.tif")
    new = raster(tmp_path,"new.tif",modified=True)
    gain = spectral_change(old,new,"old","new",4,1,.2,64)
    assert gain["valid_pixels"] == 4096
    assert gain["gain_pixels"] == 1024
    assert gain["loss_pixels"] == 0
    assert gain["features"][0]["properties"]["class_name"] == "index_gain"
    assert gain["acquired_at"] == ["2026-01-01","2026-11-01"]
    loss = spectral_change(new,old,"new","old",4,1,.2,64)
    assert loss["loss_pixels"] == 1024
    assert loss["gain_pixels"] == 0
    assert loss["features"][0]["properties"]["class_name"] == "index_loss"


def test_no_overlap_and_invalid_band_mappings_fail_cleanly(tmp_path):
    old = raster(tmp_path,"old.tif")
    shifted = raster(tmp_path,"shift.tif",modified=True,
                     origin=from_origin(100,20,.00001,.00001))
    with pytest.raises(RasterError,match="overlapping"):
        spectral_change(old,shifted,"old","far",4,1,.2,64)
    with pytest.raises(RasterError,match="distinct"):
        spectral_index(old,"old","ndvi",1,1)
    with pytest.raises(RasterError,match="unavailable"):
        spectral_index(old,"old","ndvi",5,1)
    with pytest.raises(RasterError,match="different"):
        spectral_change(old,old,"old","old",4,1)


def test_remote_sensing_jobs_require_admin_and_keep_project_isolation(tmp_path):
    path=raster(tmp_path,"new.tif",modified=True)
    image=upload(path)
    project=client.post("/projects",json={"name":"GeoAI sample"}).json()["id"]
    other=client.post("/projects",json={"name":"Independent"}).json()["id"]
    payload={"image_id":image,"index":"ndvi","first_band":4,
             "second_band":1,"threshold":.3,"max_side":64}
    no_token=client.post(f"/projects/{project}/jobs",json={
        "kind":"spectral_index","payload":payload,
    })
    assert no_token.status_code == 403
    result=complete(project,"spectral_index",payload)
    assert result["status"] == "completed",result
    assert result["result"]["features"][0]["properties"]["image_id"]==image
    assert client.get(f"/projects/{other}/jobs/{result['id']}").status_code==404
    # Analysis does not silently persist unreviewed polygons.
    assert client.get(f"/projects/{project}/features").json()["total"]==0
    invalid=complete(project,"spectral_index",
                     {"image_id":image,"first_band":1,"second_band":1})
    assert invalid["status"]=="failed"
    assert client.get(f"/projects/{project}/features").json()["total"]==0


def test_server_managed_model_catalog_and_semantic_polygons(monkeypatch,tmp_path):
    root=tmp_path/"vision-models"
    root.mkdir()
    (root/"landcover.onnx").write_bytes(b"placeholder bytes; mocked inference")
    (root/"landcover.json").write_text(json.dumps({
        "classes":["background","building","road"],
        "bands":[1,2,3],"tile_size":128,"input_scale":100,
        "mean":[0,0,0],"std":[1,1,1],
    }),encoding="utf-8")
    assert models()["models"][0]["id"]=="landcover"
    assert "model_path" not in models()["models"][0]
    assert client.get("/vision/models/segmentation").json()["models"][0]["classes"][1]=="building"
    calls=[]
    def fake(tile,config,device):
        calls.append((tile.shape,device))
        mask=np.zeros((128,128),dtype=np.uint8)
        mask[8:32,8:32]=1
        return mask,np.ones((128,128),dtype=np.float32)*.98
    monkeypatch.setattr("vision.semantic._predict_tile",fake)
    path=raster(tmp_path,"raster.tif")
    output=semantic_segmentation(path,"image","landcover",.5,64)
    assert calls==[((1,3,128,128),"cpu")]
    assert output["provider"]=="onnxruntime"
    assert output["classified_pixels"]==24*24
    assert len(output["features"])==1
    assert output["features"][0]["properties"]["class_name"]=="building"
    assert output["features"][0]["properties"]["model_id"]=="landcover"
    assert output["mean_model_confidence"]==pytest.approx(.98)
    with pytest.raises(RasterError):
        semantic_segmentation(path,"image","../../unsafe",.5,64)


def test_onnx_output_contract_rejects_wrong_shape(monkeypatch,tmp_path):
    from vision.semantic import _predict_tile
    import vision.semantic as sem
    root=tmp_path/"vision-models"
    root.mkdir()
    (root/"sample.onnx").write_bytes(b"x")
    (root/"sample.json").write_text(json.dumps({
        "classes":["background","building"],"bands":[1,2,3],"tile_size":128,
    }))
    config=sem._manifest("sample")
    class Fake:
        def get_inputs(self):
            return [type("Input",(),{"name":"raster"})()]
        def run(self,_,feed):
            return [np.zeros((1,2,50,50),dtype=np.float32)]
    monkeypatch.setattr(sem,"_session",lambda *args:Fake())
    with pytest.raises(RasterError,match="Model output"):
        _predict_tile(np.zeros((1,3,128,128),dtype=np.float32),config,"cpu")
