"""Validation-only selection followed by a frozen, region-disjoint holdout comparison."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import numpy as np
from scipy import ndimage as ndi
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape

from imagery.raster import RasterError
from imagery.store import file_sha256
from .building_dataset import load_dataset, canonical_sha
from .building_prediction import predict_image
from .building_instances import separate_components
from .building_evaluate import object_metrics
from .quality import confusion_matrix, metrics_from_matrix
from .semantic import _manifest


def polygons_from_ids(ids, minimum_pixels=1):
    if np.asarray(ids).ndim != 2 or not np.issubdtype(np.asarray(ids).dtype, np.integer):
        raise RasterError("Instance labels must be an integer grid.")
    result = []
    for geometry, value in shapes(np.asarray(ids, np.int32), mask=ids > 0, connectivity=4):
        polygon = shape(geometry)
        if polygon.area >= minimum_pixels:
            if not polygon.is_valid:
                raise RasterError("Instance polygonization produced an invalid reference geometry.")
            result.append(polygon)
        if len(result) > 20000:
            raise RasterError("Too many instances for the scientific comparison.")
    return result


def boundary_scores(predicted, reference, valid, tolerance=2):
    p = predicted & ~ndi.binary_erosion(predicted)
    t = reference & ~ndi.binary_erosion(reference)
    # Exclude unknown labels and their tolerance neighborhood from boundary scoring.
    eligible = ndi.binary_erosion(valid, iterations=tolerance, border_value=1)
    p &= eligible
    t &= eligible
    pred_count, truth_count = int(p.sum()), int(t.sum())
    matched_p = int((p & (ndi.distance_transform_edt(~t) <= tolerance)).sum()) if truth_count else 0
    matched_t = int((t & (ndi.distance_transform_edt(~p) <= tolerance)).sum()) if pred_count else 0
    precision = matched_p/pred_count if pred_count else 0.
    recall = matched_t/truth_count if truth_count else 0.
    return {"tolerance_pixels": tolerance, "predicted_boundary_pixels": pred_count,
        "reference_boundary_pixels": truth_count, "matched_predicted_pixels": matched_p,
        "matched_reference_pixels": matched_t, "precision": precision, "recall": recall,
        "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.}


def score_fields(fields, row, threshold=.5, instance_mode="connected", seed_distance=6):
    with rasterio.open(row["paths"]["labels"]) as source:
        reference = source.read(1, masked=True)
    valid = fields["valid"] & ~np.ma.getmaskarray(reference)
    observed = valid & (fields["probability"] >= threshold)
    truth = reference.data == 1
    matrix = confusion_matrix(reference.data, observed.astype(np.uint8), 2, valid)
    if row["paths"].get("instances"):
        with rasterio.open(row["paths"]["instances"]) as source:
            source_ids = np.where(valid, source.read(1), 0)
            unique = np.unique(source_ids)
            reference_ids = np.searchsorted(unique, source_ids).astype(np.int32) + (0 if unique[0] == 0 else 1)
        reference_type = "independently_supplied_instance_labels"
    else:
        reference_ids = ndi.label(truth & valid)[0]
        reference_type = "connected_semantic_reference_not_true_instances"
    if instance_mode == "watershed":
        predicted_ids = separate_components(observed, np.maximum(fields["probability"], 0),
            fields.get("boundary"), fields.get("distance"), seed_distance=seed_distance)
    elif instance_mode == "connected":
        predicted_ids = ndi.label(observed)[0]
    else:
        raise RasterError("Unsupported study instance mode.")
    # The same minimum-pixel filter is fixed for both postprocessors.
    predicted_polygons = polygons_from_ids(predicted_ids, minimum_pixels=9)
    reference_polygons = polygons_from_ids(reference_ids)
    metrics = metrics_from_matrix(matrix, ["background", "building"])
    metrics["objects_50"] = object_metrics(predicted_polygons, reference_polygons, .5)
    metrics["objects_75"] = object_metrics(predicted_polygons, reference_polygons, .75)
    metrics["object_reference"] = reference_type
    metrics["boundary"] = boundary_scores(observed, truth & valid, valid)
    p = fields["probability"][valid].astype(np.float64)
    y = truth[valid].astype(np.float64)
    metrics["brier_score"] = float(np.mean((p-y)**2)) if len(p) else None
    bins = []
    for index in range(10):
        selected = (p >= index/10) & ((p < (index+1)/10) if index < 9 else (p <= 1))
        bins.append({"lower": index/10, "upper": (index+1)/10, "pixels": int(selected.sum()),
            "mean_probability": float(p[selected].mean()) if selected.any() else None,
            "observed_frequency": float(y[selected].mean()) if selected.any() else None})
    metrics["calibration"] = {"bins": bins, "ece": sum(b["pixels"]*abs(b["mean_probability"]-b["observed_frequency"])
        for b in bins if b["pixels"])/max(1, len(p)), "confidence_calibrated": False}
    return metrics, predicted_ids


def aggregate(records):
    matrix = sum((np.asarray(r["metrics"]["confusion_matrix"], np.int64) for r in records), np.zeros((2, 2), np.int64))
    result = metrics_from_matrix(matrix, ["background", "building"])
    for key in ("objects_50", "objects_75"):
        tp = sum(r["metrics"][key]["true_positive"] for r in records)
        fp = sum(r["metrics"][key]["false_positive"] for r in records)
        fn = sum(r["metrics"][key]["false_negative"] for r in records)
        result[key] = {"true_positive": tp, "false_positive": fp, "false_negative": fn,
            "precision": tp/(tp+fp) if tp+fp else 0., "recall": tp/(tp+fn) if tp+fn else 0.,
            "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.}
    pixels = result["valid_pixels"]
    result["brier_score"] = sum(r["metrics"]["brier_score"]*r["metrics"]["valid_pixels"] for r in records)/pixels if pixels else None
    result["ece"] = sum(r["metrics"]["calibration"]["ece"]*r["metrics"]["valid_pixels"] for r in records)/pixels if pixels else None
    result["ece_aggregation"] = "valid-pixel-weighted mean of per-image ECE; not pooled calibration bins"
    result["boundary_f1_image_mean"] = float(np.mean([r["metrics"]["boundary"]["f1"] for r in records])) if records else None
    return result


def _identity(identifier):
    config = _manifest(identifier)
    return {"id": identifier, "model_sha256": file_sha256(config["model_path"]),
            "manifest_sha256": file_sha256(config["model_path"].with_suffix(".json"))}


def compare_models(dataset_path, model_ids, destination, *, evaluate_test=True, progress=None, cancelled=None):
    if not isinstance(model_ids, list) or not 2 <= len(model_ids) <= 5 or len(set(model_ids)) != len(model_ids):
        raise RasterError("Compare two to five distinct installed building models.")
    dataset = load_dataset(dataset_path)
    identities = [_identity(identifier) for identifier in model_ids]
    destination = Path(destination)
    if destination.exists():
        raise RasterError("Comparison run already exists; preserve its frozen selection receipt.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    selections, validation, holdout = {}, {}, {}

    reported_progress = 0.

    def tick(value):
        nonlocal reported_progress
        reported_progress = max(reported_progress, value)
        if cancelled:
            cancelled()
        if progress:
            progress(reported_progress)

    with TemporaryDirectory(prefix="."+destination.name+"-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        fields_root = stage / "fields"
        fields_root.mkdir()
        validation_rows = [r for r in dataset["samples"] if r["split"] == "validation"]
        thresholds = [.25, .35, .45, .5, .55, .65, .75]
        for model_index, identifier in enumerate(model_ids):
            predictions = []
            for index, row in enumerate(validation_rows):
                tick(.4*(model_index+index/len(validation_rows))/len(model_ids))
                fields = predict_image(row["paths"]["image"], identifier, progress=lambda _: tick(reported_progress))
                path = fields_root / f"validation-{model_index}-{index}.npz"
                np.savez_compressed(path, **fields)
                predictions.append(path)
            threshold_scores = []
            for threshold in thresholds:
                matrix = np.zeros((2, 2), np.int64)
                for row, path in zip(validation_rows, predictions):
                    with np.load(path) as fields, rasterio.open(row["paths"]["labels"]) as source:
                        truth = source.read(1, masked=True)
                        valid = fields["valid"] & ~np.ma.getmaskarray(truth)
                        matrix += confusion_matrix(truth.data, (fields["probability"] >= threshold).astype(np.uint8), 2, valid)
                threshold_scores.append({"threshold": threshold, "building_f1": metrics_from_matrix(matrix, ["background", "building"])["classes"][1]["f1"]})
            selected_threshold = max(threshold_scores, key=lambda s: (s["building_f1"], -abs(s["threshold"]-.5), s["threshold"]))["threshold"]
            alternatives = []
            for mode, seed_distance in [("connected", 6), ("watershed", 4), ("watershed", 6), ("watershed", 8)]:
                records = []
                for row, path in zip(validation_rows, predictions):
                    tick(.45)
                    with np.load(path) as fields:
                        metrics, _ = score_fields(fields, row, selected_threshold, mode, seed_distance)
                    records.append({"sample_id": row["id"], "region": row["region"], "metrics": metrics})
                alternatives.append({"instance_mode": mode, "seed_distance": seed_distance,
                    "aggregate": aggregate(records), "records": records})
            selected = max(alternatives, key=lambda a: (a["aggregate"]["objects_50"]["f1"], a["instance_mode"] == "connected", -a["seed_distance"]))
            selections[identifier] = {"probability_threshold": selected_threshold,
                "instance_mode": selected["instance_mode"], "seed_distance": selected["seed_distance"]}
            validation[identifier] = {"threshold_search": threshold_scores, "selected": selected,
                "postprocess_search": [{k: v for k, v in item.items() if k != "records"} for item in alternatives]}
        best_model = max(model_ids, key=lambda identifier: (validation[identifier]["selected"]["aggregate"]["classes"][1]["f1"],
            validation[identifier]["selected"]["aggregate"]["objects_50"]["f1"]))
        plan = {"dataset_fingerprint": dataset["fingerprint"], "models": identities, "parameters": selections,
            "selected_model_by_validation": best_model, "threshold_candidates": thresholds,
            "selection_rule": "validation building pixel F1; object F1 only breaks model ties and selects postprocessing",
            "test_used_for_selection": False}
        plan["sha256"] = canonical_sha(plan)
        # Selection is written before the first test image/label is scored.
        (stage / "selection.json").write_text(json.dumps(plan, indent=2)+"\n", encoding="utf-8")
        if [_identity(identifier) for identifier in model_ids] != identities:
            raise RasterError("Model bytes changed during validation selection.")
        test_rows = [r for r in dataset["samples"] if r["split"] == "test"]
        if evaluate_test:
            for model_index, identifier in enumerate(model_ids):
                records = []
                for index, row in enumerate(test_rows):
                    tick(.5+.45*(model_index+index/len(test_rows))/len(model_ids))
                    fields = predict_image(row["paths"]["image"], identifier, progress=lambda _: tick(reported_progress))
                    parameters = selections[identifier]
                    metrics, ids = score_fields(fields, row, parameters["probability_threshold"],
                                                parameters["instance_mode"], parameters["seed_distance"])
                    # Keep per-scene evidence for both mask and object mistakes.
                    path = stage / f"test-{model_index}-{index}.npz"
                    np.savez_compressed(path, probability=fields["probability"], instances=ids, valid=fields["valid"])
                    records.append({"sample_id": row["id"], "region": row["region"], "group": row["group"], "metrics": metrics})
                holdout[identifier] = {"aggregate": aggregate(records), "records": records,
                    "by_region": {region: aggregate([r for r in records if r["region"] == region]) for region in sorted({r["region"] for r in records})}}
        if load_dataset(dataset_path, verify_pixels=False)["fingerprint"] != dataset["fingerprint"] or [_identity(identifier) for identifier in model_ids] != identities:
            raise RasterError("Study source/model bytes changed before results were committed.")
        report = {"schema": "geofathom-building-comparison-1", "dataset_fingerprint": dataset["fingerprint"],
            "counts": dataset["counts"], "regions": dataset["regions"], "selection": plan,
            "validation": validation, "test": holdout, "test_evaluated": evaluate_test,
            "seconds": round(time.monotonic()-started, 3), "model_ranking_source": "validation only",
            "independence": "City-disjoint for this study; candidate pretraining corpora must be audited separately.",
            "qualification": "Small public-data study, not a universal accuracy guarantee; inspect regional failures and source bias."}
        (stage / "comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        import shutil
        shutil.rmtree(fields_root)
        tick(1.)
        stage.replace(destination)
    return report
