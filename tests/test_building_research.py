"""Frozen split integrity, real adaptation/export and operator study lifecycle.

Compact numerical fixtures verify behavior; their scores are never public-data accuracy.
"""
import copy
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from imagery.raster import RasterError
from imagery.store import file_sha256
from vision.building_dataset import canonical_sha, freeze_dataset, load_dataset, audit_dataset
from vision.building_research_store import package_dataset, import_dataset_package


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    root = tmp_path / "dataset"
    root.mkdir()
    rows = []
    for index in range(6):
        split = ("train", "validation", "test")[index//2]
        image, label, instances = root/f"image-{index}.tif", root/f"labels-{index}.tif", root/f"instances-{index}.tif"
        rgb = np.full((3, 64, 64), 10+index, np.uint8)
        rgb[0] = 0
        rgb[0, 16:48, 16:48] = 255
        ids = np.zeros((64, 64), np.int32)
        ids[16:48, 16:32] = 1
        ids[16:48, 32:48] = 2
        profile = dict(driver="GTiff", width=64, height=64, crs="EPSG:32617",
                       transform=from_origin(500000+index*10000, 4500000, 1, 1))
        for path, values in ((image, rgb), (label, (ids>0).astype(np.uint8)[None]), (instances, ids[None])):
            with rasterio.open(path, "w", **profile, count=values.shape[0], dtype=values.dtype) as dst:
                dst.write(values)
        row = {"id": f"scene-{index}", "region": split+"-city", "group": f"source-{index}", "split": split,
               "coordinate_space": "georeferenced", "image": image.name, "labels": label.name, "instances": instances.name}
        for key, path in (("image", image), ("labels", label), ("instances", instances)):
            row[key+"_sha256"] = file_sha256(path)
        rows.append(row)
    path = freeze_dataset(root, rows, provenance={"source": "numerical regression fixture"})
    monkeypatch.setenv("GEOFATHOM_BUILDING_DATASETS_DIR", str(tmp_path/"catalog"))
    monkeypatch.setenv("GEOFATHOM_BUILDING_RESEARCH_RESULTS_DIR", str(tmp_path/"runs"))
    monkeypatch.setenv("GEOFATHOM_VISION_MODELS_DIR", str(tmp_path/"models"))
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH", str(tmp_path/"projects.sqlite"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "building-research-test")
    monkeypatch.setenv("GEOFATHOM_VISION_DEVICE", "cpu")
    monkeypatch.setenv("GEOFATHOM_RASTER_ISOLATE", "0")
    return path


@pytest.fixture
def models(dataset):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("safetensors")
    from vision.building_training import make_network, export_model
    from vision.semantic import model_directory
    root = model_directory()
    root.mkdir()
    torch.manual_seed(73)
    torch.set_num_threads(2)
    manifest = {"task": "building_extraction", "architecture": "compact_unet", "classes": ["background", "building"],
        "bands": [1, 2, 3], "tile_size": 128, "halo": 16, "input_scale": 255., "mean": [0, 0, 0], "std": [1, 1, 1],
        "output_type": "binary_logits", "output_channels": 3, "output_channel": 0, "boundary_channel": 1, "distance_channel": 2}
    network = make_network("compact_unet")
    for index, identifier in enumerate(("numerical-base", "numerical-alternative")):
        with torch.no_grad():
            network.segmentation_head.bias[0] += index*.2
        directory = root / identifier
        export_model(network, directory, manifest)
        for name, suffix in (("model.onnx", ".onnx"), ("model.json", ".json"), ("model.safetensors", ".safetensors")):
            (directory/name).replace(root/(identifier+suffix))
        directory.rmdir()
    return ["numerical-base", "numerical-alternative"]


@pytest.mark.parametrize("shared", ["region", "group"])
def test_cross_split_regions_and_source_scenes_are_rejected(dataset, shared):
    definition = json.loads(dataset.read_text())
    definition["samples"][-1][shared] = definition["samples"][0][shared]
    definition["fingerprint"] = canonical_sha({k: v for k, v in definition.items() if k != "fingerprint"})
    with pytest.raises(RasterError, match="leakage"):
        audit_dataset(definition, dataset.parent)


def test_source_bytes_and_assignments_are_frozen(dataset):
    value = load_dataset(dataset)
    assert value["counts"] == {"train": 2, "validation": 2, "test": 2}
    image = value["samples"][0]["paths"]["image"]
    with image.open("ab") as out:
        out.write(b"changed")
    with pytest.raises(RasterError, match="SHA-256"):
        load_dataset(dataset)


def test_duplicate_images_and_escaping_sources_are_rejected(dataset):
    definition = json.loads(dataset.read_text())
    row = definition["samples"][-1]
    row["image"] = definition["samples"][0]["image"]
    row["image_sha256"] = definition["samples"][0]["image_sha256"]
    with pytest.raises(RasterError, match="Duplicate image"):
        audit_dataset(definition, dataset.parent)
    row["image"] = "../outside.tif"
    with pytest.raises(RasterError, match="inside"):
        audit_dataset(definition, dataset.parent)


def test_dataset_package_rejects_zip_traversal_and_preserves_fingerprint(dataset, tmp_path):
    package = tmp_path/"study.zip"
    package_dataset(dataset, package)
    result = import_dataset_package(package)
    assert result["id"] == load_dataset(dataset)["fingerprint"]
    assert import_dataset_package(package)["id"] == result["id"]
    malformed = tmp_path/"unsafe.zip"
    with zipfile.ZipFile(malformed, "w") as archive:
        archive.writestr("../escaped", b"bad")
        archive.writestr("dataset.json", dataset.read_bytes())
    with pytest.raises(RasterError, match="unsafe"):
        import_dataset_package(malformed)
    assert not (tmp_path/"escaped").exists()


def test_real_decoder_adaptation_never_reads_test_samples_and_exports_verified_heads(dataset, models, monkeypatch, tmp_path):
    from vision import building_training as training
    original = training.load_sample
    seen = []
    def checked(row, config):
        assert row["split"] != "test"
        seen.append(row["split"])
        return original(row, config)
    monkeypatch.setattr(training, "load_sample", checked)
    output = tmp_path/"fitted"
    result = training.train_model(dataset, {"initial_model_id": models[0], "mode": "decoder", "epochs": 4,
        "batch_size": 2, "learning_rate": .01}, output)
    assert set(seen) == {"train", "validation"}
    assert result["test_used_for_training"] is False
    assert result["selected_validation_loss"] <= result["initial_validation_loss"]
    assert result["onnx_parity"]["passed"]
    assert result["trainable_parameters"] > 1000
    metadata = json.loads((output/"model.json").read_text())
    assert metadata["boundary_channel"] == 1 and metadata["distance_channel"] == 2
    from vision.building_research_store import install_training_model
    installed = install_training_model(output, "adapted-numerical")
    assert installed["installed"]
    with pytest.raises(RasterError, match="exists"):
        install_training_model(output, "adapted-numerical")


def test_selection_receipt_is_frozen_before_any_test_image_is_predicted(dataset, models, monkeypatch, tmp_path):
    from vision import building_study as study
    original = study.predict_image
    audit = load_dataset(dataset)
    test_paths = {row["paths"]["image"] for row in audit["samples"] if row["split"] == "test"}
    receipts = []
    def checked(path, identifier, **kwargs):
        if path in test_paths:
            files = list(tmp_path.glob(".comparison-*/selection.json"))
            assert len(files) == 1
            receipt = json.loads(files[0].read_text())
            assert receipt["test_used_for_selection"] is False
            assert identifier in receipt["calibration"]
            assert receipt["calibration"][identifier]["validation_pixels"] == 2*64*64
            receipts.append(receipt["sha256"])
        return original(path, identifier, **kwargs)
    monkeypatch.setattr(study, "predict_image", checked)
    output = tmp_path/"comparison"
    result = study.compare_models(dataset, models, output)
    assert receipts and len(set(receipts)) == 1
    assert result["model_ranking_source"] == "validation only"
    assert result["test_evaluated"] and len(result["test"]) == 2
    assert result["selection"]["sha256"] == receipts[0]


@pytest.mark.parametrize("isolate", ["0", "1"])
def test_managed_training_download_install_and_project_isolation(dataset, models, tmp_path, monkeypatch, isolate):
    from fastapi.testclient import TestClient
    from core.main import app
    monkeypatch.setenv("GEOFATHOM_RASTER_ISOLATE", isolate)
    client = TestClient(app)
    headers = {"X-GeoFathom-Admin-Token": "building-research-test"}
    package = tmp_path/"study.zip"
    package_dataset(dataset, package)
    assert client.get("/vision/buildings/research").status_code == 403
    response = client.post("/vision/buildings/datasets", files={"file": ("study.zip", package.read_bytes(), "application/zip")}, headers=headers)
    assert response.status_code == 201, response.text
    study_id = response.json()["id"]
    project = client.post("/projects", json={"name": "Training"}).json()["id"]
    other = client.post("/projects", json={"name": "Other"}).json()["id"]
    url = f"/projects/{project}/jobs"
    submitted = client.post(url, json={"kind": "building_train", "payload": {"dataset_id": study_id,
        "training": {"initial_model_id": models[0], "epochs": 1, "batch_size": 2}}}, headers=headers)
    assert submitted.status_code == 202, submitted.text
    uid = submitted.json()["id"]
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        job = client.get(url+"/"+uid).json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(.05)
    assert job["status"] == "completed", job
    assert job["result"]["test_used_for_training"] is False
    download = url+"/"+uid+"/download"
    assert client.get(download).headers["content-type"] == "application/zip"
    assert client.get(f"/projects/{other}/jobs/{uid}/download").status_code == 404
    installed = client.post(url+"/"+uid+"/install-building-model", headers=headers)
    assert installed.status_code == 200, installed.text
    assert client.post(url+"/"+uid+"/install-building-model", headers=headers).status_code == 422
    assert client.get(download+"?asset=../outside").status_code == 404


def test_cpu_environment_is_never_reported_as_verified_cuda(monkeypatch, tmp_path):
    ort = pytest.importorskip("onnxruntime")
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    from scripts.building_gpu_acceptance import accept
    result = accept("not-loaded", "not-read.tif", output=tmp_path/"gpu.json")
    assert result["status"] == "unavailable"
    assert not result["passed"] and not result["hardware_verified"]


def test_sparse_instance_ids_have_bounded_training_targets():
    from vision.building_training import targets
    ids = np.zeros((32, 32), np.int64)
    ids[4:20, 4:20] = 2**40
    compact = (ids > 0).astype(np.int32)
    assert np.array_equal(targets(compact, ids), targets(compact, compact))


def test_gpu_instance_partition_compares_geometry_not_ids():
    from scripts.building_gpu_acceptance import partition_agreement
    a = np.array([[1, 1, 0, 2, 2], [1, 1, 0, 2, 2]])
    b = np.where(a == 1, 2, np.where(a == 2, 1, 0))
    assert partition_agreement(a, b)["passed"]
    b[0, 0] = 0
    assert not partition_agreement(a, b)["passed"]


def test_joint_operating_point_balances_objects_without_large_pixel_loss():
    from vision.building_study import choose_operating_point
    def candidate(threshold, pixel, objects, balanced):
        return {"probability_threshold": threshold, "seed_distance": 6, "instance_mode": "connected",
            "aggregate": {"classes": [{}, {"f1": pixel}], "objects_75": {"f1": objects}},
            "balanced": {"balanced_f1": balanced, "region_macro_object_f1": objects}}
    highest_pixel = candidate(.25, .82, .30, .44)
    balanced = candidate(.5, .80, .65, .72)
    unacceptable = candidate(.75, .70, .90, .79)
    assert choose_operating_point([highest_pixel, balanced, unacceptable]) is balanced


def test_training_augmentation_preserves_supervision_and_is_seeded():
    from vision.building_training import augment_training_pair
    import numpy as np
    x = np.arange(24, dtype=np.float32).reshape(3, 2, 4)
    y = x.copy()
    first = augment_training_pair(x, y, np.random.default_rng(731))
    second = augment_training_pair(x, y, np.random.default_rng(731))
    np.testing.assert_array_equal(first[0], first[1])
    np.testing.assert_array_equal(first[0], second[0])
    assert first[0].flags.c_contiguous and first[1].flags.c_contiguous
    np.testing.assert_array_equal(x, y)


def test_temperature_calibration_pools_validation_and_does_not_refit_test():
    from vision.building_calibration import TemperatureFit, ProbabilityDiagnostics
    # The intentionally overconfident model is correct on three out of four
    # equally confident predictions. Smoothing should lower validation NLL.
    p = np.array([.99, .99, .01, .01])
    y = np.array([1, 0, 0, 0])
    fit = TemperatureFit()
    fit.update(p[:2], y[:2])
    fit.update(p[2:], y[2:])
    receipt = fit.result()
    assert receipt["fitted"] and receipt["temperature"] > 1
    assert receipt["selected_nll"] < receipt["raw_nll"]
    raw, scaled = ProbabilityDiagnostics(), ProbabilityDiagnostics()
    raw.update(p, y)
    scaled.update(p, y, receipt["temperature"])
    assert scaled.result()["negative_log_likelihood"] < raw.result()["negative_log_likelihood"]
    assert scaled.result()["selective_error"][0]["error_rate"] == raw.result()["selective_error"][0]["error_rate"]
    assert sum(b["pixels"] for b in scaled.result()["bins"]) == 4
    assert fit.result() == receipt


def test_pooled_calibration_handles_empty_support_and_no_positive_labels():
    from vision.building_calibration import TemperatureFit, ProbabilityDiagnostics
    fit, diagnostics = TemperatureFit(), ProbabilityDiagnostics()
    assert fit.result()["fitted"] is False
    assert diagnostics.result()["pooled_ece"] is None
    fit.update(np.array([.2, .5]), np.array([0, 0]))
    assert fit.result()["temperature"] == 1.
    diagnostics.update(np.array([.2, .8]), np.array([0, 1]))
    assert diagnostics.result()["pooled_ece"] == pytest.approx(.2)
