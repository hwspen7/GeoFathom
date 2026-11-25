"""Reproducible public-data smoke benchmark for the deployed building workflow.

Uses original author archives, not lossy dataset-viewer previews. The upstream
post-processing search included HOT test chips, so these results are explicitly
not an independent generalization qualification.
"""
import argparse
import json
from pathlib import Path
import sys
import tarfile
from urllib.request import urlopen

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from imagery.store import file_sha256
from vision.buildings import extract_buildings
from vision.building_evaluate import evaluate_outputs
from vision.quality import metrics_from_matrix

REVISION = "8d3e64e5c69aa37209953cce3a48df1092bc7c94"
DATASET = "https://huggingface.co/datasets/hotosm/vhr-building-segmentation"
# Four projects in the published test split; no labels influence chip selection.
PROJECTS = {
    10655: ("Tajikistan", 13794742, "cce17fcfe0c4030554f9fe47d8160828a4f2e00380b26133cb463c99953abeb3"),
    14859: ("Japan", 24412956, "fb4533f32be87490c86d6a504df8a3c368abded41cb0d53ce243343e1e846752"),
    17127: ("Eswatini", 47690439, "acaaf8a62d51026af22e0dfbaccfefcd2584dc25d440eb3c1bab44f86554d8f9"),
    29145: ("Peru", 14063939, "9720a55b6f26b58ec642d390f626b57a316c632dcfab828c66484e748ed083a6"),
}


def obtain(root, project):
    country, size, expected = PROJECTS[project]
    destination = root / f"project{project}.tar.gz"
    if not destination.exists():
        temp = destination.with_suffix(".part")
        try:
            with urlopen(f"{DATASET}/resolve/{REVISION}/raw/project_{project}/data.tar.gz", timeout=60) as response, temp.open("wb") as out:
                count = 0
                while block := response.read(1024*1024):
                    count += len(block)
                    if count > size:
                        raise ValueError("Public archive exceeded pinned size.")
                    out.write(block)
            if temp.stat().st_size != size or file_sha256(temp) != expected:
                raise ValueError("Public archive failed SHA-256 verification.")
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)
    if file_sha256(destination) != expected:
        raise ValueError("Cached archive failed SHA-256 verification.")
    return destination


def _figure(samples, destination):
    from matplotlib.figure import Figure
    from matplotlib.colors import ListedColormap
    fig = Figure(figsize=(10, 2.2*len(samples)), layout="constrained")
    axes = fig.subplots(len(samples), 4, squeeze=False)
    for row, (image, labels, output, title) in enumerate(samples):
        with rasterio.open(image) as source, rasterio.open(labels) as truth, rasterio.open(output / "mask.tif") as prediction:
            rgb = source.read([1, 2, 3]).transpose(1, 2, 0)
            t, p = truth.read(1) == 1, prediction.read(1) == 1
        error = np.where(t & p, 1, np.where(p, 2, np.where(t, 3, 0)))
        for ax, data, label in zip(axes[row], [rgb, t, p, error],
                                   [title, "Reference", "Prediction", "Errors: TP green, FP red, FN blue"]):
            # Fixed categorical limits keep FP red even when a tile has no FN cells.
            style = ({"cmap": ListedColormap(["white", "#287d3c", "#cb3030", "#2363a1"]), "vmin": 0, "vmax": 3}
                     if label.startswith("Errors") else {"cmap": "gray", "vmin": 0, "vmax": 1} if data.ndim == 2 else {})
            ax.imshow(data, **style)
            ax.set_title(label, fontsize=8)
            ax.set_axis_off()
    fig.savefig(destination, dpi=160)


def deny_network():
    """Linux offline verification denies socket syscalls before loading a model.

    This also blocks native-library telemetry; Python-only socket mocks do not.
    The filter applies only to this benchmark process and its descendants.
    """
    import ctypes
    from ctypes.util import find_library
    if sys.platform != "linux":
        raise RuntimeError("Kernel-enforced offline benchmark currently requires Linux.")
    library = find_library("seccomp")
    if library is None:
        raise RuntimeError("libseccomp is required for the offline benchmark.")
    lib = ctypes.CDLL(library)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7fff0000)
    if not context:
        raise RuntimeError("Cannot initialize offline syscall filter.")
    try:
        for name in (b"socket", b"connect", b"sendto", b"sendmsg", b"sendmmsg"):
            number = lib.seccomp_syscall_resolve_name(name)
            if number < 0 or lib.seccomp_rule_add(context, 0x00050001, number, 0) != 0:
                raise RuntimeError("Cannot configure offline syscall filter.")
        if lib.seccomp_load(context) != 0:
            raise RuntimeError("Cannot enforce offline syscall filter.")
    finally:
        lib.seccomp_release(context)


def run(root, model_id="hotosm-dinov3s-buildings", per_project=3, offline=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if not 1 <= per_project <= 20:
        raise ValueError("Choose 1–20 deterministic chips per project.")
    if offline:
        for project in PROJECTS:
            if not (root / f"project{project}.tar.gz").is_file():
                raise ValueError("Download all pinned archives before offline evaluation.")
        deny_network()
    records, visual = [], []
    total = np.zeros((2, 2), np.int64)
    for project, (country, _, digest) in PROJECTS.items():
        archive = obtain(root, project)
        with tarfile.open(archive) as tar:
            members = {m.name.removeprefix("./"): m for m in tar.getmembers() if m.isfile()}
            chips = sorted(n for n in members if n.startswith("chips/") and n.endswith(".tif"))
            chosen = np.linspace(0, len(chips)-1, per_project, dtype=int)
            for index in chosen:
                name = chips[index]
                tile = Path(name).stem
                directory = root / str(project) / tile
                directory.mkdir(parents=True, exist_ok=True)
                # Extract only named regular members into fixed filenames; never tar.extractall.
                for key, filename in [(name, "original.tif"), (name+".aux.xml", "original.tif.aux.xml"),
                    ("masks/"+tile+".tif", "original-labels.tif"),
                    ("labels/"+tile+".geojson", "reference.geojson")]:
                    if key in members:
                        with tar.extractfile(members[key]) as inp:
                            (directory / filename).write_bytes(inp.read())
                    elif not key.endswith(".aux.xml"):
                        raise ValueError("Public archive lacks a required chip or label.")
                image, truth = directory / "image.tif", directory / "labels.tif"
                # Original OAM chips are sometimes JPEG bytes named .tif with an author
                # georeferencing sidecar. Repackage losslessly on exactly that grid.
                with rasterio.open(directory / "original.tif") as src:
                    if not src.crs:
                        raise ValueError("Author chip has no recoverable georeferencing.")
                    profile = dict(driver="GTiff", width=src.width, height=src.height,
                        crs=src.crs, transform=src.transform, compress="deflate")
                    with rasterio.open(image, "w", **profile, count=3, dtype="uint8") as dst:
                        dst.write(src.read([1, 2, 3]))
                with rasterio.open(directory / "original-labels.tif") as src:
                    if (src.crs, src.transform, src.width, src.height) != (
                            profile["crs"], profile["transform"], profile["width"], profile["height"]):
                        raise ValueError("Author image and label grids differ.")
                    values = src.read(1)
                    if not np.isin(values, [0, 1, 255]).all():
                        raise ValueError("Unknown public binary mask encoding.")
                    with rasterio.open(truth, "w", **profile, count=1, dtype="uint8") as dst:
                        dst.write((values > 0).astype(np.uint8), 1)
                output = directory / "outputs"
                if output.exists():
                    raise ValueError("Benchmark output already exists; use a fresh run directory.")
                result = extract_buildings(image, {"image_id": tile, "model_id": model_id}, output)
                metrics = evaluate_outputs(output, truth, directory / "reference.geojson")
                total += np.asarray(metrics["confusion_matrix"], np.int64)
                record = {"project_id": project, "country": country, "tile": tile,
                    "original_image_sha256": file_sha256(directory / "original.tif"),
                    "sidecar_sha256": file_sha256(directory / "original.tif.aux.xml") if (directory / "original.tif.aux.xml").exists() else None,
                    "metrics": metrics, "summary": result["summary"], "seconds": result["seconds"],
                    "model_sha256": result["model_sha256"], "manifest_sha256": result["manifest_sha256"]}
                records.append(record)
                print(country, tile, "building F1", round(metrics["classes"][1]["f1"], 4), flush=True)
                if int(index) == int(chosen[len(chosen)//2]):
                    visual.append((image, truth, output, country+" / "+tile))
    report = {"dataset": DATASET, "revision": REVISION, "split": "test-project subset",
        "sampling": f"{per_project} evenly spaced chips from sorted archive names per project, including empty scenes",
        "archives_sha256": {str(k): v[2] for k, v in PROJECTS.items()},
        "model_id": model_id, "aggregate": metrics_from_matrix(total, ["background", "building"]),
        "records": records, "independent_generalization_qualified": False,
        "limitations": ["Small public-data integration sample; no accuracy pass threshold.",
            "Upstream post-processing tuning included HOT train/test chips; this is not an untouched external test.",
            "Connected regions can merge touching buildings; per-object metrics score retained polygons separately.",
            "Labels originate from OSM and may be incomplete or temporally misaligned."],
        "attribution": "Imagery: contributors of Open Imagery Network / OpenAerialMap (CC-BY-4.0). Labels: OpenStreetMap contributors (ODbL-1.0). Dataset: HOT."}
    (root / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    _figure(visual, root / "public-comparison.png")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="hotosm-dinov3s-buildings")
    parser.add_argument("--per-project", type=int, default=3)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.download_only:
        args.output.mkdir(parents=True, exist_ok=True)
        for project in PROJECTS:
            print(obtain(args.output, project), flush=True)
        return
    report = run(args.output, args.model, args.per_project, args.offline)
    print(json.dumps(report["aggregate"], indent=2))


if __name__ == "__main__":
    main()
