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


@pytest.mark.parametrize("enhanced", [False, True])
def test_real_decoder_adaptation_never_reads_test_samples_and_exports_verified_heads(dataset, models, monkeypatch, tmp_path, enhanced):
    from vision import building_training as training
    original = training.load_sample
    seen = []
    def checked(row, config):
        assert row["split"] != "test"
        seen.append(row["split"])
        return original(row, config)
    monkeypatch.setattr(training, "load_sample", checked)
    output = tmp_path/"fitted"
    result = training.train_model(dataset, {"initial_model_id": models[0], "mode": "decoder", "epochs": 4, "enhanced_training": enhanced, "objective": "hard_examples" if enhanced else "standard",
        "batch_size": 2, "learning_rate": .01}, output)
    assert set(seen) == {"train", "validation"}
    assert result["test_used_for_training"] is False
    assert result["selected_validation_loss"] <= result["initial_validation_loss"]
    assert result["onnx_parity"]["passed"]
    assert result["parameters"]["objective"] == ("hard_examples" if enhanced else "standard")
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
    assert result["selection"]["paired_baseline"]["probability_threshold"] == .5
    for model in models:
        assert result["test"][model]["paired_qualification"]["status"] == "insufficient_evidence"
        assert len(result["test"][model]["fixed_baseline"]["records"]) == 2


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


def test_instance_boundary_metric_penalizes_missed_shared_wall():
    from vision.building_study import boundary_scores
    reference = np.zeros((48, 48), np.int32)
    reference[4:44, 4:24] = 1
    reference[4:44, 24:44] = 2
    merged = (reference > 0).astype(np.int32)
    valid = np.ones(reference.shape, bool)
    assert boundary_scores(merged > 0, reference > 0, valid)["f1"] == 1.
    assert boundary_scores(merged, reference, valid, instances=True)["f1"] < 1.
    assert boundary_scores(reference, reference, valid, instances=True)["f1"] == 1.


def test_paired_building_gate_uses_source_groups_and_rejects_regional_regression():
    from vision.building_qualification import paired_gate
    def record(region, group, suffix, tp):
        return {"sample_id": f"{region}-{group}-{suffix}", "region": region, "group": f"{region}-{group}",
                "metrics": {"confusion_matrix": [[90, 10], [10, 90]],
                    "object_reference": "independently_supplied_instance_labels",
                    **{key: {"true_positive": tp, "false_positive": 10-tp, "false_negative": 10-tp}
                       for key in ("objects_50", "objects_75")}}}
    baseline = [record(r, i, 0, 6) for r in ("a", "b") for i in range(10)]
    candidate = [record(r, i, 0, 8) for r in ("a", "b") for i in range(10)]
    report = paired_gate(baseline, candidate)
    assert report["passed"] and report["metrics"]["object_f1"]["delta"] == pytest.approx(.2)
    assert report["metrics"]["object_f1"]["paired_group_bootstrap_95_interval"] == pytest.approx([.2, .2])
    assert paired_gate(baseline[:10], candidate[:10])["status"] == "insufficient_evidence"
    worse = [record(r, i, 0, 9 if r == "a" else 5) for r in ("a", "b") for i in range(10)]
    assert not paired_gate(baseline, worse)["checks"]["regional_noninferiority"]
    with pytest.raises(ValueError, match="identical"):
        paired_gate(baseline, candidate[:-1])
    # Two chips from one source still count as only one source group.
    repeat_a = [record(r, 0, i, 6) for r in ("a", "b") for i in range(10)]
    repeat_b = [record(r, 0, i, 8) for r in ("a", "b") for i in range(10)]
    assert paired_gate(repeat_a, repeat_b)["status"] == "insufficient_evidence"


@pytest.mark.parametrize('foreground', ['empty','full','mixed'])
def test_objective_finite_and_all_heads_receive_gradient(foreground):
    torch = pytest.importorskip("torch")
    from vision.building_objective import hard_example_loss
    torch.manual_seed(731)
    raw=torch.randn(2,3,16,16,requires_grad=True)
    y=torch.zeros_like(raw)
    y[:,2]=-1
    if foreground != 'empty':
        sl=slice(None) if foreground=='full' else slice(4,12)
        y[:,0,sl,sl]=1
        y[:,1,sl,sl]=1
        y[:,2,sl,sl]=.25
    loss=hard_example_loss(raw,y,torch.tensor(2.))
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(raw.grad).all()
    assert (raw.grad.abs().sum(dim=(0,2,3))>0).all()


def test_wrong_small_building_increases_objective():
    torch = pytest.importorskip("torch")
    from vision.building_objective import hard_example_loss
    y=torch.zeros(1,3,32,32); y[:,2]=-1
    y[:,0,10:13,10:13]=1; y[:,1,10:13,10:13]=1; y[:,2,10:13,10:13]=.1
    correct=torch.where(y>0,torch.tensor(8.),torch.tensor(-8.))
    missed=correct.clone(); missed[:,0,10:13,10:13]=-8
    assert hard_example_loss(missed,y,torch.tensor(2.))>hard_example_loss(correct,y,torch.tensor(2.))


def test_optimizer_decreases_objective_on_tiny_fixture():
    torch = pytest.importorskip("torch")
    from vision.building_objective import hard_example_loss
    torch.manual_seed(731)
    torch.set_num_threads(2)
    y=torch.zeros(1,3,16,16); y[:,2]=-1
    y[:,0,5:10,6:9]=1; y[:,1,5:10,6:9]=1; y[:,2,5:10,6:9]=.25
    raw=torch.nn.Parameter(torch.zeros_like(y)); opt=torch.optim.Adam([raw],lr=.2)
    initial=hard_example_loss(raw,y,torch.tensor(2.)).item()
    for _ in range(25):
        opt.zero_grad(); loss=hard_example_loss(raw,y,torch.tensor(2.)); loss.backward(); opt.step()
    assert hard_example_loss(raw,y,torch.tensor(2.)).item()<initial*.5


def test_ensemble_freezes_weights_before_test_and_returns_deployment_parameters(dataset, models, monkeypatch, tmp_path):
    from vision import building_ensemble_study as study
    original = study.predict_image
    test_paths = {row["paths"]["image"] for row in load_dataset(dataset)["samples"] if row["split"]=="test"}
    receipts = []
    def checked(path, identifier, **kwargs):
        if path in test_paths:
            selection = list(tmp_path.glob(".ensemble-*/selection.json"))
            assert len(selection)==1
            receipt = json.loads(selection[0].read_text())
            assert receipt["test_used_for_selection"] is False
            receipts.append(receipt["sha256"])
        return original(path, identifier, **kwargs)
    monkeypatch.setattr(study,"predict_image",checked)
    report=study.compare_ensemble(dataset,models,tmp_path/"ensemble",evaluate_test=True)
    assert len(receipts)==4 and len(set(receipts))==1
    assert report["selection"]["sha256"]==receipts[0]
    assert report["deployment_parameters"]["secondary_weight"] in (.25,.5,.75)
    assert report["holdout"]["qualification"]["status"]=="insufficient_evidence"
    assert report["qualified"] is False


def test_ensemble_probability_contract_rejects_invalid_values_and_support():
    from vision.building_ensemble import fuse_probabilities
    from vision.building_ensemble_study import ensemble_fields
    a=np.array([[.1,.8,-1]],np.float32); b=np.array([[.7,.2,-1]],np.float32)
    valid=a>=0
    np.testing.assert_allclose(fuse_probabilities(a,b,.25,valid),[[.25,.65,-1]],atol=1e-7)
    with pytest.raises(RasterError):
        fuse_probabilities(a,b,1.2,valid)
    with pytest.raises(RasterError):
        fuse_probabilities(a,np.full_like(b,np.nan),.5,valid)
    with pytest.raises(RasterError,match="inconsistent"):
        ensemble_fields({"probability":a,"valid":valid},{"probability":b,"valid":~valid},.5)


def test_size_stratification_uses_global_matching_and_reference_support():
    from shapely.geometry import box
    from vision.building_evaluate import object_metrics
    truth = [box(0,0,5,5),box(20,0,28,8),box(40,0,60,20)]
    predicted = [box(20,0,27,8),box(40,0,60,20),box(80,0,84,4)]
    metrics = object_metrics(predicted,truth,.5,pixel_size_breakdown=True)
    sizes = metrics["size_breakdown"]
    assert metrics["true_positive"]==2
    assert sizes["small"]["reference_count"]==1 and sizes["small"]["recall"]==0
    assert sizes["small"]["predicted_count"]==2 and sizes["small"]["precision"]==.5
    assert sizes["medium"]["recall"]==1 and sizes["medium"]["precision"] is None
    assert sizes["large"]["recall"]==sizes["large"]["precision"]==1
    empty = object_metrics([],truth,.5,pixel_size_breakdown=True)["size_breakdown"]
    assert empty["small"]["recall"]==0 and empty["small"]["precision"] is None


def test_confidence_fusion_is_bounded_and_preserves_unanimity_and_nodata():
    from vision.building_ensemble import fuse_probabilities, uncertainty_fields
    a=np.array([[.1,.5,1.,0.,-1]],np.float32)
    b=np.array([[.9,.9,1.,0.,-1]],np.float32)
    valid=a>=0
    fixed=fuse_probabilities(a,b,.5,valid)
    adaptive=fuse_probabilities(a,b,.5,valid,mode="confidence")
    assert adaptive[0,1]>fixed[0,1]
    np.testing.assert_allclose(adaptive[0,[0,2,3,4]],fixed[0,[0,2,3,4]],atol=1e-7)
    assert np.all(adaptive[valid]>=np.minimum(a,b)[valid])
    assert np.all(adaptive[valid]<=np.maximum(a,b)[valid])
    d,e=uncertainty_fields(a,b,adaptive,valid)
    assert d[0,0]==pytest.approx(.8)
    assert e[0,0]==pytest.approx(1.)
    assert e[0,2]==e[0,3]==0 and d[0,4]==e[0,4]==-1
    with pytest.raises(RasterError,match="Unsupported"):
        fuse_probabilities(a,b,.5,valid,mode="unknown")


def test_ensemble_candidate_grid_includes_adaptive_and_fixed_controls(dataset,models,tmp_path):
    from vision.building_ensemble_study import compare_ensemble
    report=compare_ensemble(dataset,models,tmp_path/"adaptive-grid")
    grid=report["selection"]["candidate_grid"]
    assert len(grid)==120
    assert {r["instance_mode"] for r in grid}=={"connected","watershed","adaptive"}
    assert {r["fusion_mode"] for r in grid}=={"fixed","confidence"}
    assert not report["test_evaluated"] and report["holdout"] is None


def test_building_profile_binds_models_and_parameters(dataset,models,tmp_path):
    from vision.building_ensemble_study import compare_ensemble
    from vision.building_profile import verify_profile
    from vision.semantic import _manifest
    report=compare_ensemble(dataset,models,tmp_path/"profile-study")
    profile=json.loads((tmp_path/"profile-study"/"profile.json").read_text())
    parameters=report["deployment_parameters"]
    manifests=[_manifest(identifier) for identifier in models]
    assert profile["reported_qualification"]=="validation_only"
    receipt=verify_profile(profile,parameters,manifests)
    assert receipt["qualification_verified"] is False
    with pytest.raises(RasterError,match="parameters changed"):
        verify_profile(profile,{**parameters,"secondary_weight":.95},manifests)
    modified={**profile,"reported_qualification":"passed_paired_gate"}
    with pytest.raises(RasterError,match="digest mismatch"):
        verify_profile(modified,parameters,manifests)
    path=manifests[0]["model_path"].with_suffix(".json")
    path.write_text(path.read_text()+"\n")
    with pytest.raises(RasterError,match="model bytes"):
        verify_profile(profile,parameters,manifests)
