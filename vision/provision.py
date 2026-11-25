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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="hotosm-dinov3s-buildings")
    args = parser.parse_args()
    print(json.dumps(install(args.model), indent=2))


if __name__ == "__main__":
    main()
