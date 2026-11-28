"""Operator-owned frozen study packages and immutable training/comparison runs."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
from tempfile import TemporaryDirectory
from uuid import UUID
import zipfile

from imagery.raster import RasterError
from imagery.store import file_sha256
from storage.snapshots import copy_verified
from .building_dataset import load_dataset
from .semantic import model_directory, _MODEL_NAME

_DIGEST = re.compile(r"^[a-f0-9]{64}$")


def dataset_root():
    return Path(os.getenv("GEOFATHOM_BUILDING_DATASETS_DIR") or
                Path(__file__).resolve().parents[1] / "data/building-datasets").resolve()


def dataset_path(identifier):
    if not isinstance(identifier, str) or not _DIGEST.fullmatch(identifier):
        raise RasterError("Invalid frozen building dataset identifier.")
    path = dataset_root() / identifier / "dataset.json"
    if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        raise FileNotFoundError("Building dataset not found.")
    return path


def dataset_catalog():
    result = []
    for path in sorted(dataset_root().glob("*/dataset.json"))[:100]:
        if path.is_symlink() or path.parent.is_symlink():
            continue
        dataset = load_dataset(path, verify_pixels=False)
        result.append({"id": dataset["fingerprint"], "counts": dataset["counts"],
            "regions": dataset["regions"], "provenance": dataset["definition"].get("provenance", {})})
    return {"datasets": result}


def import_dataset_package(package):
    root = dataset_root()
    root.mkdir(parents=True, exist_ok=True)
    if Path(package).stat().st_size > 256*1024**2:
        raise RasterError("Building dataset ZIP exceeds 256 MiB.")
    with TemporaryDirectory(prefix=".dataset-", dir=root) as temporary, zipfile.ZipFile(package) as archive:
        stage = Path(temporary)
        members = archive.infolist()
        if len(members) > 3001 or sum(m.file_size for m in members) > 512*1024**2:
            raise RasterError("Building study package exceeds its file or expanded-size allowance.")
        names = set()
        for member in members:
            if member.is_dir():
                continue
            relative = Path(member.filename)
            if (relative.is_absolute() or ".." in relative.parts or "\\" in member.filename
                    or ":" in member.filename or stat.S_ISLNK(member.external_attr >> 16)
                    or member.filename in names or member.file_size > 32*1024**2):
                raise RasterError("Building package has an unsafe, duplicate or oversized source entry.")
            names.add(member.filename)
        if "dataset.json" not in names or archive.getinfo("dataset.json").file_size > 2*1024**2:
            raise RasterError("Place the frozen dataset.json at the ZIP root.")
        definition = json.loads(archive.read("dataset.json"))
        samples = definition.get("samples", [])
        if not isinstance(samples, list) or not 3 <= len(samples) <= 1000:
            raise RasterError("Invalid building study sample list.")
        required = {"dataset.json"}
        for row in samples:
            if not isinstance(row, dict):
                raise RasterError("Invalid building study sample.")
            for key in ("image", "labels", "instances"):
                if row.get(key):
                    if not isinstance(row[key], str):
                        raise RasterError("Building study sources require relative path strings.")
                    required.add(row[key])
        if not all(isinstance(name, str) and name in names for name in required):
            raise RasterError("Building package is missing declared source files.")
        for name in required:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RasterError("Dataset source path leaves its package.")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as inp, target.open("wb") as out:
                shutil.copyfileobj(inp, out, length=1024*1024)
        dataset = load_dataset(stage / "dataset.json")
        destination = root / dataset["fingerprint"]
        if destination.exists():
            if load_dataset(destination / "dataset.json")["fingerprint"] != dataset["fingerprint"]:
                raise RasterError("Existing frozen study has changed.")
        else:
            # Publish the whole immutable directory after validating every byte and assignment.
            stage.replace(destination)
    return {"id": dataset["fingerprint"], "counts": dataset["counts"], "regions": dataset["regions"]}


def result_directory(identifier):
    if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
        raise RasterError("Invalid building research task identifier.")
    root = Path(os.getenv("GEOFATHOM_BUILDING_RESEARCH_RESULTS_DIR") or
                Path(__file__).resolve().parents[1] / "data/building-research-runs").resolve()
    return root / identifier


def install_training_model(directory, identifier):
    if not isinstance(identifier, str) or not _MODEL_NAME.fullmatch(identifier):
        raise RasterError("Invalid trained building model identifier.")
    directory = Path(directory)
    root = model_directory()
    root.mkdir(parents=True, exist_ok=True)
    names = {"model.onnx": identifier+".onnx", "model.safetensors": identifier+".safetensors", "model.json": identifier+".json"}
    if any((root / name).exists() or (root / name).is_symlink() for name in names.values()):
        raise RasterError("A model with this identifier exists; trained models never overwrite installed weights.")
    metadata = json.loads((directory / "model.json").read_text(encoding="utf-8"))
    for name, key in (("model.onnx", "weights_sha256"), ("model.safetensors", "checkpoint_sha256")):
        if file_sha256(directory / name) != metadata.get(key):
            raise RasterError("Training outputs changed before installation.")
    created = []
    try:
        with TemporaryDirectory(prefix=".model-", dir=root) as temporary:
            stage = Path(temporary)
            for source, destination in names.items():
                copy_verified(directory / source, stage / destination)
            # Exclusive links prevent concurrent requests from overwriting another model.
            for destination in names.values():
                os.link(stage / destination, root / destination)
                created.append(root / destination)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {"model_id": identifier, "model_sha256": metadata["weights_sha256"], "installed": True}


def package_dataset(definition_path, destination):
    dataset = load_dataset(definition_path)
    root = Path(definition_path).resolve().parent
    files = {"dataset.json"}
    for row in dataset["samples"]:
        files.update(str(path.relative_to(root)) for path in row["paths"].values())
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(files):
            archive.write(root / relative, relative)
    return {"filename": str(destination), "sha256": file_sha256(Path(destination)), "samples": len(dataset["samples"])}


def run_managed(kind, payload, job_id, progress=None, cancelled=None):
    dataset = dataset_path(payload["dataset_id"])
    destination = result_directory(job_id)
    if kind == "building_train":
        from .building_training import train_model, trainable_checkpoint
        from storage.snapshots import _model_root
        config, checkpoint = trainable_checkpoint(payload["training"]["initial_model_id"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="."+job_id+"-input-", dir=destination.parent) as temporary:
            root = Path(temporary)
            # Capture all related model bytes; no mutable catalog path is read during fitting.
            for source in (config["model_path"], config["model_path"].with_suffix(".json"), checkpoint):
                copy_verified(source, root / source.name)
            token = _model_root.set(root)
            try:
                report = train_model(dataset, payload["training"], destination, progress=progress, cancelled=cancelled)
            finally:
                _model_root.reset(token)
        filename = "training.json"
        result = {key: report[key] for key in ("dataset_fingerprint", "counts", "regions", "best_epoch", "validation_improved",
            "initial_validation_loss", "selected_validation_loss", "test_used_for_training", "device", "seconds", "model_sha256", "onnx_parity", "history")}
        result["suggested_model_id"] = "local-building-"+job_id[:12]
    elif kind == "building_compare":
        from .building_study import compare_models
        report = compare_models(dataset, payload["model_ids"], destination, evaluate_test=payload.get("evaluate_test", True),
                                progress=progress, cancelled=cancelled, augmentation=payload.get("augmentation", "none"))
        filename = "comparison.json"
        result = {"dataset_fingerprint": report["dataset_fingerprint"], "selection": report["selection"],
            "test_evaluated": report["test_evaluated"],
            "validation": {key: value["selected"]["aggregate"] for key, value in report["validation"].items()},
            "test": {key: value["aggregate"] for key, value in report["test"].items()}, "seconds": report["seconds"]}
    else:
        raise RasterError("Unsupported building research task.")
    package = destination / "research.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(destination.iterdir()):
            if file.is_file() and file.name != "research.zip":
                archive.write(file, file.name)
    result.update({"kind": kind, "report": filename, "artifacts": {
        file.name: {"sha256": file_sha256(file), "size_bytes": file.stat().st_size}
        for file in destination.iterdir() if file.is_file() and file.suffix in (".zip", ".json", ".onnx", ".safetensors")}})
    return result
