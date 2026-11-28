"""Paired, source-group resampled building improvement evidence.

The gate is predeclared, not optimized using holdout labels. It does not prove
pretraining independence, and never installs a model or modifies its threshold.
"""
import numpy as np

POLICY = {"minimum_regions": 2, "minimum_groups_per_region": 10,
          "minimum_object_f1_gain": .01, "maximum_pixel_f1_loss": .01,
          "maximum_object75_f1_loss": .01, "maximum_region_object_f1_loss": .05,
          "bootstrap_repetitions": 1000, "bootstrap_seed": 731}


def _counts(record):
    m = record["metrics"]
    matrix = np.asarray(m["confusion_matrix"], np.int64)
    return np.array([matrix[1, 1], matrix[0, 1], matrix[1, 0],
        *(m["objects_50"][key] for key in ("true_positive", "false_positive", "false_negative")),
        *(m["objects_75"][key] for key in ("true_positive", "false_positive", "false_negative"))],
        dtype=np.int64)


def _f1(values):
    values = np.asarray(values).reshape(*np.asarray(values).shape[:-1], 3, 3)
    tp, fp, fn = values[..., 0], values[..., 1], values[..., 2]
    denominator = 2*tp+fp+fn
    return np.divide(2*tp, denominator, out=np.zeros_like(denominator, dtype=float), where=denominator>0)


def paired_gate(baseline, candidate):
    """Compare exactly the same labeled scenes; resample paired source groups."""
    first = {r["sample_id"]: r for r in baseline}
    second = {r["sample_id"]: r for r in candidate}
    if (not first or len(first) != len(baseline) or len(second) != len(candidate)
            or first.keys() != second.keys()):
        raise ValueError("Paired building evidence must contain identical unique samples.")
    grouped = {}
    has_instances = True
    for identifier in sorted(first):
        a, b = first[identifier], second[identifier]
        if (a["region"], a["group"]) != (b["region"], b["group"]):
            raise ValueError("Paired building samples have different region/source assignments.")
        if (np.asarray(a["metrics"]["confusion_matrix"]).sum(axis=1) !=
                np.asarray(b["metrics"]["confusion_matrix"]).sum(axis=1)).any():
            raise ValueError("Paired building metrics have different reference support.")
        has_instances &= all(r["metrics"].get("object_reference") ==
                             "independently_supplied_instance_labels" for r in (a, b))
        groups = grouped.setdefault(a["region"], {})
        groups.setdefault(a["group"], np.zeros((2, 9), np.int64))
        groups[a["group"]] += np.stack([_counts(a), _counts(b)])
    pooled = np.zeros((2, 9), np.int64)
    bootstrap = np.zeros((POLICY["bootstrap_repetitions"], 2, 9), np.int64)
    rng = np.random.default_rng(POLICY["bootstrap_seed"])
    regions = {}
    for region, groups in sorted(grouped.items()):
        values = np.stack([groups[key] for key in sorted(groups)])
        total = values.sum(axis=0)
        pooled += total
        # One source scene is a resampling unit; chips from it never act as
        # independent observations. Draw within each region to preserve strata.
        for i in range(POLICY["bootstrap_repetitions"]):
            indices = rng.integers(0, len(values), size=len(values))
            bootstrap[i] += values[indices].sum(axis=0)
        delta = _f1(total)[1]-_f1(total)[0]
        regions[region] = {"source_groups": len(groups), "pixel_f1_delta": float(delta[0]),
                           "object_f1_delta": float(delta[1]), "object75_f1_delta": float(delta[2])}
    values = _f1(pooled)
    delta = values[1]-values[0]
    draws = _f1(bootstrap)
    changes = draws[:, 1]-draws[:, 0]
    intervals = np.quantile(changes, [.025, .975], axis=0)
    checks = {
        "independent_instance_labels": bool(has_instances),
        "region_support": len(regions) >= POLICY["minimum_regions"],
        "source_group_support": all(r["source_groups"] >= POLICY["minimum_groups_per_region"] for r in regions.values()),
        "positive_reference_support": bool(pooled[0, 0]+pooled[0, 2] > 0 and pooled[0, 3]+pooled[0, 5] > 0),
        "object_gain": bool(delta[1] >= POLICY["minimum_object_f1_gain"]),
        "pixel_noninferiority": bool(delta[0] >= -POLICY["maximum_pixel_f1_loss"]),
        "object75_noninferiority": bool(delta[2] >= -POLICY["maximum_object75_f1_loss"]),
        "regional_noninferiority": all(r["object_f1_delta"] >= -POLICY["maximum_region_object_f1_loss"] for r in regions.values()),
        "paired_object_interval_positive": bool(intervals[0, 1] > 0),
    }
    support_keys = ("independent_instance_labels", "region_support", "source_group_support", "positive_reference_support")
    status = "insufficient_evidence" if not all(checks[key] for key in support_keys) else (
        "passed_paired_gate" if all(checks.values()) else "not_qualified")
    names = ("pixel_f1", "object_f1", "object75_f1")
    return {"status": status, "passed": status == "passed_paired_gate", "checks": checks,
            "policy": dict(POLICY), "regions": regions, "samples": len(first),
            "metrics": {name: {"baseline": float(values[0, i]), "candidate": float(values[1, i]),
                "delta": float(delta[i]), "paired_group_bootstrap_95_interval": intervals[:, i].tolist()}
                for i, name in enumerate(names)},
            "scope": "Conditional on supplied fixed holdout regions; no claim of unseen-city or pretraining independence."}
