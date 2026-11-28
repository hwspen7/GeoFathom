"""Portable ensemble parameters bound to model bytes and a frozen study receipt.

The digest detects accidental edits; it is not a signature or proof that the
author supplied independent test labels. Profiles never install or promote models.
"""
import re

from imagery.raster import RasterError
from imagery.store import file_sha256
from .building_dataset import canonical_sha

PARAMETERS = ("model_id", "secondary_model_id", "secondary_weight", "probability_threshold",
              "fusion_mode", "instance_mode", "seed_distance", "augmentation")


def create_profile(plan, deployment, qualification):
    if plan.get("sha256") != canonical_sha({k:v for k,v in plan.items() if k!="sha256"}):
        raise RasterError("Ensemble selection receipt digest mismatch.")
    payload = {"schema": "geofathom-building-profile-1",
               "dataset_fingerprint": plan["dataset_fingerprint"], "selection_sha256": plan["sha256"],
               "models": plan["models"], "parameters": {k: deployment[k] for k in PARAMETERS},
               "reported_qualification": qualification["status"] if qualification else "validation_only"}
    return {**payload, "sha256": canonical_sha(payload)}


def verify_profile(profile, parameters, manifests):
    """Reject changed parameters or model bytes; qualification remains descriptive."""
    if not isinstance(profile, dict) or set(profile) != {"schema","dataset_fingerprint","selection_sha256",
            "models","parameters","reported_qualification","sha256"}:
        raise RasterError("Invalid building profile structure.")
    if (profile["schema"] != "geofathom-building-profile-1"
            or profile["reported_qualification"] not in ("validation_only","insufficient_evidence",
                                                          "not_qualified","passed_paired_gate")
            or any(not isinstance(profile[k],str) or re.fullmatch("[0-9a-f]{64}",profile[k]) is None
                   for k in ("sha256","dataset_fingerprint","selection_sha256"))):
        raise RasterError("Invalid building profile metadata.")
    if profile["sha256"] != canonical_sha({k:v for k,v in profile.items() if k!="sha256"}):
        raise RasterError("Building profile digest mismatch.")
    if profile["parameters"] != {k:parameters[k] for k in PARAMETERS}:
        raise RasterError("Building profile parameters changed; clear profile before editing.")
    identities = [{"id": config["id"], "model_sha256": file_sha256(config["model_path"]),
                   "manifest_sha256": file_sha256(config["model_path"].with_suffix(".json"))}
                  for config in manifests]
    if profile["models"] != identities:
        raise RasterError("Building profile model bytes no longer match the frozen study.")
    return {"sha256":profile["sha256"], "selection_sha256":profile["selection_sha256"],
            "dataset_fingerprint":profile["dataset_fingerprint"],
            "reported_qualification":profile["reported_qualification"],
            "qualification_verified":False}
