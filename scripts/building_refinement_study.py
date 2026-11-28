"""Validation-only experiment: fixed baseline, fragment repair and hybrid views."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision.building_dataset import load_dataset
from vision.building_ensemble_study import ensemble_fields
from vision.building_prediction import predict_image
from vision.building_refinement import (merge_fragments, overlap_diagnostics, hybrid_fields,
                                        joint_ridge, refine_mask, grouped_temperature_nll)
from vision.building_study import score_fields, aggregate, _identity
from vision.building_calibration import TemperatureFit, TEMPERATURES


def run(dataset_path, models, output, device):
    if output.exists():
        raise ValueError("Preserve the existing experiment output.")
    dataset = load_dataset(dataset_path)
    identities = [_identity(m) for m in models]
    rows = [r for r in dataset["samples"] if r["split"] == "validation"]
    records = {}
    calibration = {}
    group_fits = {}

    def collect(name, fields, row, reference, mode="adaptive", repair=False, threshold=.35, mask=None):
        metrics, ids = score_fields(fields, row, threshold, mode, 6, mask_override=mask)
        if repair:
            ids = merge_fragments(ids, np.maximum(fields["probability"], 0), fields.get("boundary"))
            metrics, _ = score_fields(fields, row, threshold, mode, 6, instance_override=ids, mask_override=mask)
        records.setdefault(name, []).append({"sample_id": row["id"], "metrics": metrics,
            "overlap": overlap_diagnostics(ids, reference)})

    for index, row in enumerate(rows):
        print(f"Validation {index+1}/{len(rows)}: {row['id']}", flush=True)
        fields = {}
        for augmentation in ("flips", "multiscale"):
            a, b = [predict_image(row["paths"]["image"], m, device=device, augmentation=augmentation)
                    for m in models]
            fields[augmentation] = ensemble_fields(a, b, .5, "fixed")
        fields["hybrid"] = hybrid_fields(fields["flips"], fields["multiscale"])
        with rasterio.open(row["paths"]["labels"]) as src:
            truth = src.read(1, masked=True)
        valid = fields["flips"]["valid"] & ~np.ma.getmaskarray(truth)
        if row["paths"].get("instances"):
            with rasterio.open(row["paths"]["instances"]) as src:
                reference = np.where(valid, src.read(1), 0)
        else:
            reference = ndi.label(valid & (truth.data == 1))[0]
        for name, f in fields.items():
            fit = calibration.setdefault(name, TemperatureFit())
            fit.update(f["probability"][valid], truth.data[valid])
            group = group_fits.setdefault(name, {}).setdefault(row["group"], TemperatureFit())
            group.update(f["probability"][valid], truth.data[valid])
            collect(name+"_adaptive", f, row, reference)
            collect(name+"_repair", f, row, reference, repair=True)
            guided = {**f, "boundary": joint_ridge(f["probability"], f.get("boundary"), f.get("distance"), valid)}
            collect(name+"_joint_ridge", guided, row, reference)
            collect(name+"_joint_repair", guided, row, reference, repair=True)
            mask = refine_mask(f["probability"], valid, .35, f.get("boundary"))
            collect(name+"_contour", guided, row, reference, repair=True, mask=mask)
        collect("flips_connected", fields["flips"], row, reference, mode="connected")
        collect("flips_watershed", fields["flips"], row, reference, mode="watershed")
        oracle = {"valid": fields["flips"]["valid"], "probability": (truth.data == 1).astype(np.float32)}
        collect("oracle_mask_connected", oracle, row, reference, mode="connected", threshold=.5)
    if [_identity(m) for m in models] != identities or load_dataset(dataset_path, verify_pixels=False)["fingerprint"] != dataset["fingerprint"]:
        raise ValueError("Experiment inputs changed.")
    report = {"dataset_fingerprint": dataset["fingerprint"], "models": identities, "device": device,
              "test_used": False, "parameters": {"weight": .5, "threshold": .35, "seed_distance": 6,
                  "hybrid_scale_weight": .35, "fragment_fraction": .25, "ridge_limit": .35},
              "calibration_validation_fit": {k: v.result() for k, v in calibration.items()},
              "calibration_group_crossfit": {k: grouped_temperature_nll(v, TEMPERATURES) for k, v in group_fits.items()},
              "results": {k: {"aggregate": aggregate(v), "records": v} for k, v in records.items()},
              "note": "Exploratory validation only; oracle is not deployable. Overlap counts are diagnostic, not causal or mutually exclusive. Calibration fit is not independently verified."}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    for k, v in report["results"].items():
        a = v["aggregate"]
        print(f"{k:24} pixel={a['classes'][1]['f1']:.5f} object50={a['objects_50']['f1']:.5f} object75={a['objects_75']['f1']:.5f}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    run(args.dataset, args.models, args.output, args.device)
