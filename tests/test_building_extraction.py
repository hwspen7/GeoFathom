"""Real ONNX transport, native-grid boundaries, nodata, AOI and artifact isolation.

The tiny graph is a numerical fixture, never evidence of real building accuracy.
"""
import json
import time
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import mapping, box, shape

from imagery.raster import RasterError
from vision.buildings import extract_buildings, validate
from vision.semantic import _manifest, _predict_tile


@pytest.fixture
def setup(tmp_path, monkeypatch):
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import helper, numpy_helper, TensorProto
    root = tmp_path / "models"
    root.mkdir()
    # The auxiliary channels are deliberately huge so softmax would be wrong.
    weights = np.zeros((3, 3, 1, 1), np.float32)
    weights[0, 0, 0, 0] = 20
    bias = np.array([-10, 100, 100], np.float32)
    graph = helper.make_graph([helper.make_node("Conv", ["x", "w", "b"], ["y"])],
        "numerical-fixture", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 128, 128])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3, 128, 128])],
        [numpy_helper.from_array(weights, "w"), numpy_helper.from_array(bias, "b")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.save(model, root / "numerical.onnx")
    (root / "numerical.json").write_text(json.dumps({
        "classes": ["background", "building"], "task": "building_extraction",
        "tile_size": 128, "halo": 16, "output_type": "binary_logits",
        "output_channels": 3, "output_channel": 0}))
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR", str(root))
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE", "cpu")
    monkeypatch.setenv("GEOFATHOM_BUILDING_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH", str(tmp_path / "projects.sqlite"))
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR", str(tmp_path / "imagery"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "building-test")
    monkeypatch.setenv("GEOFATHOM_RASTER_ISOLATE", "0")
    # A courtyard, an object crossing several cores, and two diagonal neighbors.
    data = np.full((3, 190, 230), 20, np.uint8)
    data[0] = 0
    data[0, 25:165, 30:210] = 255
    data[0, 65:95, 75:105] = 0
    data[0, 2:6, 2:6] = 255
    data[0, 6:10, 6:10] = 255
    data[:, 180:185, :] = 99
    path = tmp_path / "scene.tif"
    transform = from_origin(500000, 4500000, 1, 1)
    with rasterio.open(path, "w", driver="GTiff", width=230, height=190, count=3,
            crs="EPSG:32617", transform=transform, dtype="uint8", nodata=99) as dst:
        dst.write(data)
    return path, tmp_path / "output", data, transform


def options(**changes):
    return {"image_id": "scene", "model_id": "numerical", "minimum_area_m2": 0.,
            "minimum_pixels": 1, **changes}


def test_auxiliary_heads_are_sigmoid_decoded_without_class_competition(setup):
    tensor = np.zeros((1, 3, 128, 128), np.float32)
    tensor[:, 0, :64] = 1
    labels, confidence = _predict_tile(tensor, _manifest("numerical"), "cpu")
    assert np.all(labels[:64] == 1) and np.all(labels[64:] == 0)
    assert np.all(confidence > .999)


def test_native_grid_seams_holes_diagonal_neighbors_and_nodata(setup):
    path, out, data, transform = setup
    result = extract_buildings(path, options(), out)
    assert len(result["features"]) == 3
    assert result["tile_count"] == 6
    assert result["valid_pixels"] == 190*230-5*230
    assert result["classified_pixels"] == 140*180-30*30+32
    with rasterio.open(out / "mask.tif") as mask:
        assert mask.transform == transform and mask.nodata == 255
        assert np.all(mask.read(1)[180:185] == 255)
        expected = ((data[0] == 255) & (data[0] != 99)).astype(np.uint8)
        actual = mask.read(1)
        np.testing.assert_array_equal(actual[actual != 255], expected[actual != 255])
    largest = result["features"][0]
    assert len(largest["geometry"]["coordinates"]) == 2
    assert largest["properties"]["mean_building_probability"] > .999
    assert largest["properties"]["perimeter_m"] > 0
    assert largest["properties"]["confidence_calibrated"] is False
    assert set(result["artifacts"]) == {"mask.tif", "probability.tif", "footprints.geojson", "footprints.csv", "areas.png", "areas.svg"}
    assert json.loads((out / "footprints.geojson").read_text())["analysis"] == "building_extraction"


def test_aoi_crops_native_grid_and_keeps_excluded_holes_invalid(setup):
    path, out, _, _ = setup
    from rasterio.warp import transform_geom
    roi = mapping(box(500010, 4499830, 500180, 4499990).difference(
                  box(500040, 4499890, 500060, 4499940)))
    aoi = transform_geom("EPSG:32617", "EPSG:4326", roi)
    result = extract_buildings(path, options(aoi=aoi), out)
    assert result["pixel_grid"][0] < 230 and result["pixel_grid"][1] < 190
    with rasterio.open(out / "mask.tif") as mask:
        assert mask.read(1, masked=True).mask.any()
        for feature in result["features"]:
            assert shape(feature["geometry"]).difference(shape(aoi).buffer(1e-7)).area < 1e-12


@pytest.mark.parametrize("change", [
    {"full_resolution": False}, {"probability_threshold": float("nan")},
    {"probability_threshold": 1.}, {"minimum_area_m2": -1.},
    {"max_features": 101}, {"max_pixels": True}, {"unknown": 1},
    {"aoi": {"type": "Point", "coordinates": [0, 0]}},
])
def test_invalid_parameters_are_rejected(change):
    with pytest.raises(ValueError):
        validate(options(**change))


def test_empty_aoi_and_cancelled_tasks_do_not_publish_artifacts(setup):
    path, out, _, _ = setup
    with pytest.raises(RasterError, match="overlap"):
        extract_buildings(path, options(aoi=mapping(box(0, 0, 1, 1))), out)
    def cancel():
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        extract_buildings(path, options(), out, cancelled=cancel)
    assert not out.exists()
    assert not list(out.parent.glob(".output-*"))


def test_empty_result_and_minimum_area_are_explicit(setup):
    path, out, _, _ = setup
    result = extract_buildings(path, options(minimum_area_m2=100000.), out)
    assert result["summary"]["candidate_count"] == 0
    assert (out / "mask.tif").exists()


def test_evaluation_keeps_missed_buildings_and_penalizes_duplicate_objects(setup):
    from vision.building_evaluate import evaluate_outputs, object_metrics
    path, out, data, transform = setup
    extract_buildings(path, options(), out)
    truth_path = out.parent / "truth.tif"
    with rasterio.open(truth_path, "w", driver="GTiff", width=230, height=190,
            count=1, dtype="uint8", crs="EPSG:32617", transform=transform, nodata=255) as dst:
        reference = (data[0] == 255).astype(np.uint8)
        reference[180:185] = 255
        # Add one reference building the deployed numerical graph misses.
        reference[12:15, 12:15] = 1
        dst.write(reference, 1)
    evaluation = evaluate_outputs(out, truth_path)
    assert evaluation["confusion_matrix"][1][0] == 9
    assert evaluation["classes"][1]["recall"] < 1
    assert evaluation["valid_pixels"] == 190*230 - 5*230
    objects = object_metrics([box(0, 0, 10, 10), box(0, 0, 10, 10)], [box(0, 0, 10, 10)])
    assert objects["true_positive"] == 1 and objects["false_positive"] == 1
    assert objects["precision"] == .5


@pytest.mark.parametrize("isolate", ["0", "1"])
def test_job_api_preserves_snapshots_project_isolation_and_checked_downloads(setup, monkeypatch, isolate):
    monkeypatch.setenv("GEOFATHOM_RASTER_ISOLATE", isolate)
    from fastapi.testclient import TestClient
    from core.main import app
    client = TestClient(app)
    path, _, _, _ = setup
    headers = {"X-GeoFathom-Admin-Token": "building-test"}
    image = client.post("/imagery/upload", files={"file": ("scene.tif", path.read_bytes(), "image/tiff")}, headers=headers)
    assert image.status_code == 201, image.text
    project = client.post("/projects", json={"name": "Building study"}).json()["id"]
    other = client.post("/projects", json={"name": "Other study"}).json()["id"]
    endpoint = f"/projects/{project}/jobs"
    body = {"kind": "building_extraction", "payload": options(image_id=image.json()["id"])}
    assert client.post(endpoint, json=body).status_code == 403
    submitted = client.post(endpoint, json=body, headers=headers)
    assert submitted.status_code == 202, submitted.text
    uid = submitted.json()["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(endpoint + "/" + uid).json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(.03)
    assert job["status"] == "completed", job
    assert job["result"]["provenance"]["task_kind"] == "building_extraction"
    assert "numerical.onnx" in job["result"]["provenance"]["model_files_sha256"]
    download = endpoint + "/" + uid + "/download"
    assert client.get(download).status_code == 200
    assert client.get(download + "?asset=probability.tif").headers["content-type"] == "image/tiff"
    assert client.get(f"/projects/{other}/jobs/{uid}/download").status_code == 404
    assert client.get(download + "?asset=../../secret").status_code == 404
    from vision.buildings import artifact_directory
    (artifact_directory(uid) / "mask.tif").write_bytes(b"changed")
    assert client.get(download + "?asset=mask.tif").status_code == 422
