"""Explicit, checksum-pinned installation of a supported public building model."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from imagery.store import file_sha256
from .semantic import model_directory, _manifest


def install(identifier="hotosm-dinov3s-buildings"):
    if identifier == "whu-unetplusplus-efficientnet-b4":
        return install_whu()
    if identifier != "hotosm-dinov3s-buildings":
        raise ValueError("Unknown public building model.")
    catalog = Path(__file__).with_name("catalog") / (identifier + ".json")
    info = json.loads(catalog.read_text(encoding="utf-8"))
    root = model_directory()
    root.mkdir(parents=True, exist_ok=True)
    weights = root / (identifier + ".onnx")
    manifest = weights.with_suffix(".json")
    if weights.is_symlink() or manifest.is_symlink():
        raise ValueError("Refusing to replace symlinked model files.")
    if weights.exists() and file_sha256(weights) != info["sha256"]:
        raise ValueError("Existing model has different bytes; move it before installing.")
    with TemporaryDirectory(prefix=".install-", dir=root) as directory:
        stage = Path(directory)
        if not weights.exists():
            digest = hashlib.sha256()
            size = 0
            with urlopen(info["download_url"], timeout=60) as response, (stage / "model.onnx").open("wb") as out:
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > info["size_bytes"]:
                        raise ValueError("Downloaded model exceeds its pinned size.")
                    digest.update(block)
                    out.write(block)
            if size != info["size_bytes"] or digest.hexdigest() != info["sha256"]:
                raise ValueError("Downloaded model failed SHA-256 verification.")
            (stage / "model.onnx").replace(weights)
        (stage / "model.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        (stage / "model.json").replace(manifest)
    _manifest(identifier)
    return {"model_id": identifier, "sha256": info["sha256"], "installed": True}


def install_whu():
    """Convert only the pinned author state_dict, using tensor-only deserialization."""
    import torch
    from .building_training import make_network, export_model
    identifier = "whu-unetplusplus-efficientnet-b4"
    info = json.loads((Path(__file__).with_name("catalog") / (identifier+".json")).read_text())
    root = model_directory()
    root.mkdir(parents=True, exist_ok=True)
    if any((root / (identifier+suffix)).exists() for suffix in (".onnx", ".json", ".safetensors")):
        raise ValueError("Model identifier already exists; preserve it or choose a separate model directory.")
    with TemporaryDirectory(prefix=".whu-", dir=root) as temporary:
        stage = Path(temporary)
        source = stage / "author.pth"
        digest = hashlib.sha256()
        count = 0
        with urlopen(info["download_url"], timeout=60) as inp, source.open("wb") as out:
            while block := inp.read(1024*1024):
                count += len(block)
                if count > info["size_bytes"]:
                    raise ValueError("Author checkpoint exceeds its pinned size.")
                digest.update(block)
                out.write(block)
        if count != info["size_bytes"] or digest.hexdigest() != info["sha256"]:
            raise ValueError("Author checkpoint SHA-256 verification failed.")
        state = torch.load(source, map_location="cpu", weights_only=True)
        weights, bias = state["segmentation_head.0.weight"], state["segmentation_head.0.bias"]
        if weights.shape[0] != 2 or bias.shape != (2,):
            raise ValueError("Author checkpoint class head differs from the declared model.")
        adapted = torch.zeros((3, *weights.shape[1:]), dtype=weights.dtype)
        adapted[0] = weights[1]-weights[0]
        state["segmentation_head.0.weight"] = adapted
        state["segmentation_head.0.bias"] = torch.tensor([float(bias[1]-bias[0]), -2., 0.], dtype=bias.dtype)
        network = make_network(info["architecture"])
        network.load_state_dict(state, strict=True)
        torch.set_num_threads(2)
        metadata = {**info, "conversion": "exact foreground-minus-background logit margin; auxiliary heads disabled until adaptation"}
        parity = export_model(network, stage / "converted", metadata)
        for source_name, suffix in (("model.onnx", ".onnx"), ("model.safetensors", ".safetensors"), ("model.json", ".json")):
            (stage / "converted" / source_name).replace(root / (identifier+suffix))
    return {"model_id": identifier, "author_sha256": info["sha256"],
            "onnx_sha256": file_sha256(root / (identifier+".onnx")), "export_parity": parity, "installed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="hotosm-dinov3s-buildings")
    parser.add_argument("--from-training", type=Path, help="Install an extracted model.onnx/model.json/model.safetensors training bundle.")
    args = parser.parse_args()
    if args.from_training:
        from .building_research_store import install_training_model
        result = install_training_model(args.from_training, args.model)
    else:
        result = install(args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
