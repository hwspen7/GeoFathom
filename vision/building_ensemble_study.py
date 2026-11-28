"""Validation-selected ensemble recipe, with an untouched paired holdout comparison."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from imagery.raster import RasterError
from .building_dataset import load_dataset, canonical_sha
from .building_ensemble import compatible_members, fuse_probabilities
from .building_prediction import predict_image
from .building_qualification import POLICY, paired_gate
from .building_study import _identity, aggregate, balanced_validation_score, score_fields
from .semantic import _manifest


def ensemble_fields(primary, secondary, weight, mode="fixed"):
    if not np.array_equal(primary["valid"], secondary["valid"]):
        raise RasterError("Ensemble members have inconsistent source support.")
    if weight == 0:
        return primary
    if weight == 1:
        return secondary
    return {**primary, "probability": fuse_probabilities(
        primary["probability"], secondary["probability"], weight, primary["valid"], mode=mode)}


def choose_recipe(candidates):
    """Select operating points independently for single-model and fused candidates."""
    best_pixel = max(item["aggregate"]["classes"][1]["f1"] for item in candidates)
    eligible = [item for item in candidates if item["aggregate"]["classes"][1]["f1"] >= best_pixel-.03-1e-12]
    return max(eligible, key=lambda item: (
        item["balanced"]["balanced_f1"], item["balanced"]["region_macro_object_f1"],
        item["aggregate"]["objects_75"]["f1"], -abs(item["threshold"]-.5),
        item["instance_mode"] == "connected", item.get("fusion_mode", "fixed") == "fixed",
        -abs(item["weight"]-.5), -item["seed_distance"]))


def compare_ensemble(dataset_path, model_ids, destination, *, augmentation="none",
                     evaluate_test=False, progress=None, cancelled=None):
    if len(model_ids) != 2 or len(set(model_ids)) != 2:
        raise RasterError("Choose two distinct building models for ensemble comparison.")
    if augmentation not in ("none", "flips", "multiscale"):
        raise RasterError("Unsupported ensemble inference mode.")
    compatible_members(*[_manifest(identifier) for identifier in model_ids])
    identities = [_identity(identifier) for identifier in model_ids]
    dataset = load_dataset(dataset_path)
    destination = Path(destination)
    if destination.exists():
        raise RasterError("Ensemble study outputs already exist.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    recipes = [{"weight": weight, "threshold": threshold, "instance_mode": mode,
                "seed_distance": seed, "fusion_mode": fusion}
               for weight in (0., .25, .5, .75, 1.)
               for fusion in (("fixed",) if weight in (0., 1.) else ("fixed", "confidence"))
               for threshold in (.35, .5, .65)
               for mode, seed in (("connected", 6), ("watershed", 6), ("watershed", 10), ("adaptive", 6), ("adaptive", 10))]
    validation = [[] for _ in recipes]
    rows = [r for r in dataset["samples"] if r["split"] == "validation"]

    def tick(value):
        if cancelled is not None:
            cancelled()
        if progress is not None:
            progress(value)

    def predict_pair(row, value):
        return [predict_image(row["paths"]["image"], identifier, augmentation=augmentation,
                              progress=lambda _: tick(value)) for identifier in model_ids]

    def score(fields, row, recipe):
        metrics, _ = score_fields(fields, row, recipe["threshold"],
                                  recipe["instance_mode"], recipe["seed_distance"])
        return {"sample_id": row["id"], "region": row["region"], "group": row["group"], "metrics": metrics}

    with TemporaryDirectory(prefix=".ensemble-", dir=destination.parent) as temp:
        stage = Path(temp)
        for i, row in enumerate(rows):
            value = .6*i/len(rows)
            tick(value)
            primary, secondary = predict_pair(row, value)
            for weight, fusion in sorted({(r["weight"], r["fusion_mode"]) for r in recipes}):
                fields = ensemble_fields(primary, secondary, weight, fusion)
                for j, recipe in enumerate(recipes):
                    if recipe["weight"] == weight and recipe["fusion_mode"] == fusion:
                        tick(value)
                        validation[j].append(score(fields, row, recipe))
        candidates = [{**recipe, "aggregate": aggregate(records), "balanced": balanced_validation_score(records)}
                      for recipe, records in zip(recipes, validation)]
        baseline = choose_recipe([item for item in candidates if item["weight"] in (0., 1.)])
        candidate = choose_recipe([item for item in candidates if 0 < item["weight"] < 1])
        parameter_keys = ("weight", "threshold", "instance_mode", "seed_distance", "fusion_mode")
        plan = {"dataset_fingerprint": dataset["fingerprint"], "models": identities,
                "augmentation": augmentation, "baseline": {k: baseline[k] for k in parameter_keys},
                "candidate": {k: candidate[k] for k in parameter_keys},
                "candidate_grid": recipes, "qualification_policy": dict(POLICY),
                "test_used_for_selection": False, "auxiliary_heads": "primary_only_for_fusion"}
        plan["sha256"] = canonical_sha(plan)
        (stage/"selection.json").write_text(json.dumps(plan, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        if [_identity(identifier) for identifier in model_ids] != identities:
            raise RasterError("Ensemble model bytes changed during validation selection.")
        holdout = None
        if evaluate_test:
            test = [r for r in dataset["samples"] if r["split"] == "test"]
            base_records, fused_records = [], []
            for i, row in enumerate(test):
                value = .6+.35*i/len(test)
                tick(value)
                primary, secondary = predict_pair(row, value)
                base_records.append(score(ensemble_fields(primary, secondary, baseline["weight"]), row, baseline))
                fused_records.append(score(ensemble_fields(primary, secondary, candidate["weight"], candidate["fusion_mode"]), row, candidate))
            holdout = {"baseline": aggregate(base_records), "candidate": aggregate(fused_records),
                       "baseline_records": base_records, "candidate_records": fused_records,
                       "qualification": paired_gate(base_records, fused_records)}
        if (load_dataset(dataset_path, verify_pixels=False)["fingerprint"] != dataset["fingerprint"]
                or [_identity(identifier) for identifier in model_ids] != identities):
            raise RasterError("Ensemble study inputs changed before publication.")
        deployment = {"model_id": model_ids[0], "secondary_model_id": model_ids[1],
                      "secondary_weight": candidate["weight"], "probability_threshold": candidate["threshold"],
                      "fusion_mode": candidate["fusion_mode"],
                      "instance_mode": candidate["instance_mode"], "seed_distance": candidate["seed_distance"],
                      "augmentation": augmentation}
        report = {"selection": plan, "validation": candidates, "holdout": holdout,
                  "deployment_parameters": deployment, "test_evaluated": evaluate_test,
                  "qualified": bool(holdout and holdout["qualification"]["passed"]),
                  "note": "Validation-selected candidate only; never auto-promoted. Prior holdout use and pretraining overlap require separate audit."}
        (stage/"ensemble.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        tick(1.)
        stage.replace(destination)
    return report
