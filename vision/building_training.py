"""Local, reproducible building head/decoder adaptation with untouched test data."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
import rasterio
from scipy import ndimage as ndi
from typing import Literal

from imagery.raster import RasterError
from imagery.store import file_sha256
from .building_dataset import load_dataset
from .semantic import _manifest, model_directory


class TrainingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    initial_model_id: str = Field(min_length=1, max_length=64)
    mode: Literal["head", "decoder"] = "head"
    epochs: int = Field(default=12, ge=1, le=100)
    batch_size: int = Field(default=4, ge=1, le=16)
    learning_rate: float = Field(default=.001, gt=0, le=.05, allow_inf_nan=False)
    seed: int = Field(default=731, ge=0, le=2147483647)
    device: Literal["cpu", "cuda"] = "cpu"
    cache_mb: int = Field(default=2048, ge=32, le=8192)
    max_samples: int = Field(default=256, ge=3, le=1000)


def make_network(architecture):
    """Architecture is selected from a closed registry, never arbitrary Python code."""
    import torch
    from torch import nn
    if architecture == "unetplusplus_efficientnet_b4":
        import segmentation_models_pytorch as smp
        return smp.UnetPlusPlus(encoder_name="efficientnet-b4", encoder_weights=None, in_channels=3, classes=3)
    if architecture == "compact_unet":
        class Encoder(nn.Module):
            def __init__(self):
                super().__init__()
                self.skip = nn.Sequential(nn.Conv2d(3, 8, 3, padding=1), nn.ReLU(),
                                          nn.Conv2d(8, 8, 3, padding=1), nn.ReLU())
                self.down = nn.Sequential(nn.MaxPool2d(2), nn.Conv2d(8, 16, 3, padding=1), nn.ReLU(),
                                          nn.Conv2d(16, 16, 3, padding=1), nn.ReLU())

            def forward(self, x):
                skip = self.skip(x)
                return [skip, self.down(skip)]

        class Decoder(nn.Module):
            def __init__(self):
                super().__init__()
                self.up = nn.Sequential(nn.Conv2d(24, 8, 3, padding=1), nn.ReLU(),
                                        nn.Conv2d(8, 8, 3, padding=1), nn.ReLU())

            def forward(self, features):
                skip, bottleneck = features
                up = torch.nn.functional.interpolate(bottleneck, size=skip.shape[-2:], mode="bilinear", align_corners=False)
                return self.up(torch.cat([skip, up], dim=1))

        class Compact(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = Encoder()
                self.decoder = Decoder()
                self.segmentation_head = nn.Conv2d(8, 3, 3, padding=1)

            def forward(self, x):
                return self.segmentation_head(self.decoder(self.encoder(x)))
        return Compact()
    raise RasterError("Unsupported trainable building architecture.")


def trainable_checkpoint(identifier):
    config = _manifest(identifier)
    if config.get("architecture") is None:
        raise RasterError("This ONNX model has no supported trainable checkpoint.")
    path = model_directory() / (identifier + ".safetensors")
    if path.is_symlink() or not path.is_file() or path.resolve().parent != model_directory():
        raise RasterError("Install the matching local safetensors checkpoint before training.")
    metadata = json.loads(config["model_path"].with_suffix(".json").read_text(encoding="utf-8"))
    if metadata.get("checkpoint_sha256") != file_sha256(path) or metadata.get("weights_sha256") != file_sha256(config["model_path"]):
        raise RasterError("Trainable checkpoint or ONNX bytes differ from the paired export manifest.")
    return config, path


def targets(labels, instances=None):
    """Supervise individual boundaries, including shared walls and courtyard holes."""
    foreground = np.asarray(labels) == 1
    ids = ndi.label(foreground)[0] if instances is None else np.asarray(instances)
    # Compact sparse source IDs before find_objects, whose allocation follows max(label).
    unique = np.unique(ids)
    ids = np.searchsorted(unique, ids).astype(np.int32) + (0 if unique[0] == 0 else 1)
    boundary = np.zeros(foreground.shape, bool)
    padded = np.pad(ids, 1)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        boundary |= foreground & (padded[1+dy:1+dy+ids.shape[0], 1+dx:1+dx+ids.shape[1]] != ids)
    # Distance is positive inside each instance, negative in background, clipped at 16 pixels.
    distance = -np.minimum(ndi.distance_transform_edt(~foreground), 16).astype(np.float32)/16
    for index, window in enumerate(ndi.find_objects(ids.astype(np.int32)), 1):
        if window is None:
            continue
        local = ids[window] == index
        inside = ndi.distance_transform_edt(np.pad(local, 1))[1:-1, 1:-1]
        distance[window][local] = np.minimum(inside[local], 16)/16
    return np.stack([foreground.astype(np.float32), boundary.astype(np.float32), distance])


def load_sample(row, config):
    with rasterio.open(row["paths"]["image"]) as image, rasterio.open(row["paths"]["labels"]) as labels:
        rgb = image.read(config["bands"]).astype(np.float32)
        truth = labels.read(1, masked=True)
        valid = ~np.ma.getmaskarray(truth)
        if not valid.all():
            raise RasterError("Training chips require fully labeled pixels; crop or mask unknown labels first.")
        if np.any((rgb < 0) | (rgb > config["input_scale"])):
            raise RasterError("Training image encoding differs from the initial model.")
        ids = None
        if row["paths"].get("instances"):
            with rasterio.open(row["paths"]["instances"]) as source:
                ids = source.read(1)
        x = (rgb/config["input_scale"] - np.array(config["mean"], np.float32)[:, None, None]) / np.array(config["std"], np.float32)[:, None, None]
        return x, targets(truth.data, ids)


def export_model(network, directory, manifest, *, verify=True):
    """Export a self-contained graph and check PyTorch/ONNX head parity on held-out tensors."""
    import torch
    from safetensors.torch import save_file
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    network = network.cpu().eval()
    size = manifest["tile_size"]
    example = torch.linspace(0., 1., 3*size*size).reshape(1, 3, size, size)
    # Legacy export is explicit for supported PyTorch versions; no code is downloaded by the exporter.
    torch.onnx.export(network, example, str(directory / "model.onnx"), opset_version=17,
                      input_names=["image"], output_names=["logits"], dynamo=False)
    save_file({key: value.detach().cpu().contiguous() for key, value in network.state_dict().items()},
              str(directory / "model.safetensors"))
    parity = None
    if verify:
        import onnxruntime as ort
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        session = ort.InferenceSession(str(directory / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        with torch.inference_mode():
            expected = network(example).numpy()
        actual = session.run(None, {"image": example.numpy()})[0]
        maximum = float(np.max(np.abs(expected-actual)))
        # Deep CPU convolution graphs accumulate small backend-dependent logit differences.
        # Gate the deployed probabilities/partition and distance field, and retain raw error.
        sigmoid = lambda value: np.exp(-np.logaddexp(0., -value))
        probability_error = float(np.max(np.abs(sigmoid(expected[:, :2])-sigmoid(actual[:, :2]))))
        distance_error = float(np.max(np.abs(np.tanh(expected[:, 2])-np.tanh(actual[:, 2]))))
        mask_disagreement = float(np.mean((expected[:, 0] >= 0) != (actual[:, 0] >= 0)))
        if probability_error > .001 or distance_error > .01 or mask_disagreement > .001:
            raise RasterError("Exported building model failed PyTorch/ONNX head parity.")
        parity = {"maximum_absolute_logit_error": maximum, "maximum_probability_error": probability_error,
                  "maximum_signed_distance_error": distance_error, "mask_disagreement_fraction": mask_disagreement,
                  "limits": {"probability_error": .001, "signed_distance_error": .01, "mask_disagreement_fraction": .001},
                  "passed": True, "criterion": "deployed probability/partition parity; raw logits are diagnostic"}
    metadata = {**manifest, "weights_sha256": file_sha256(directory / "model.onnx"),
                "checkpoint_sha256": file_sha256(directory / "model.safetensors")}
    (directory / "model.json").write_text(json.dumps(metadata, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return parity


def train_model(dataset_path, options, destination, *, progress=None, cancelled=None):
    import torch
    import torch.nn.functional as F
    from safetensors.torch import load_file, save_file
    options = TrainingOptions.model_validate(options) if isinstance(options, dict) else options
    dataset = load_dataset(dataset_path)
    if len(dataset["samples"]) > options.max_samples:
        raise RasterError("Training dataset exceeds the explicitly selected sample allowance.")
    config, checkpoint = trainable_checkpoint(options.initial_model_id)
    if options.device == "cuda":
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    if options.device == "cuda" and not torch.cuda.is_available():
        raise RasterError("CUDA training was requested but no PyTorch CUDA device is available.")
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    torch.manual_seed(options.seed)
    np.random.seed(options.seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device(options.device)
    network = make_network(config["architecture"])
    # safetensors stores tensors only; loading does not execute checkpoint Python code.
    network.load_state_dict(load_file(str(checkpoint)), strict=True)
    network.to(device).eval()
    for parameter in network.parameters():
        parameter.requires_grad_(False)
    for module in ([network.segmentation_head] if options.mode == "head" else [network.decoder, network.segmentation_head]):
        for parameter in module.parameters():
            parameter.requires_grad_(True)
    optimizer = torch.optim.AdamW([p for p in network.parameters() if p.requires_grad], lr=options.learning_rate, weight_decay=.0001)
    destination = Path(destination)
    if destination.exists():
        raise RasterError("Training outputs already exist; use a new run directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def tick(fraction):
        if cancelled:
            cancelled()
        if progress:
            progress(fraction)

    with TemporaryDirectory(prefix="."+destination.name+"-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        cache = []
        bytes_cached = 0
        sample_shape = None
        # Only train/validation images are read by adaptation; test rows never enter this cache.
        rows = [r for r in dataset["samples"] if r["split"] in ("train", "validation")]
        for index, row in enumerate(rows):
            tick(.25*index/max(1, len(rows)))
            rgb, truth = load_sample(row, config)
            if sample_shape is not None and rgb.shape != sample_shape:
                raise RasterError("Training batches require chips on one common pixel shape.")
            sample_shape = rgb.shape
            if rgb.shape[1] % 32 or rgb.shape[2] % 32:
                raise RasterError("Trainable model chips must have dimensions divisible by 32.")
            if options.mode == "head":
                with torch.inference_mode():
                    features = network.decoder(network.encoder(torch.from_numpy(rgb[None]).to(device))).cpu().numpy()[0]
            else:
                features = rgb
            bytes_cached += features.nbytes + truth.nbytes
            if bytes_cached > options.cache_mb * 1024**2:
                raise RasterError("Training feature cache exceeds its explicit disk allowance.")
            a, b = stage / f"features-{index}.npy", stage / f"targets-{index}.npy"
            np.save(a, features)
            np.save(b, truth)
            cache.append((row, a, b))
        train = [r for r in cache if r[0]["split"] == "train"]
        validation = [r for r in cache if r[0]["split"] == "validation"]
        positive = sum(float(np.load(r[2], mmap_mode="r")[0].sum()) for r in train)
        population = sum(int(np.load(r[2], mmap_mode="r")[0].size) for r in train)
        if not 0 < positive < population:
            raise RasterError("Training requires both building and background labels.")
        weight = torch.tensor(min(6., max(1., (population-positive)/positive)), device=device)

        def loss_for(entries, update=False):
            total, observations = 0., 0
            for first in range(0, len(entries), options.batch_size):
                tick(.3)
                group = entries[first:first+options.batch_size]
                x = torch.from_numpy(np.stack([np.load(r[1], mmap_mode="r") for r in group])).to(device)
                y = torch.from_numpy(np.stack([np.load(r[2], mmap_mode="r") for r in group])).to(device)
                if x.numel()*x.element_size()*8 > 768*1024**2:
                    raise RasterError("Training batch exceeds the working tensor allowance.")
                with torch.set_grad_enabled(update):
                    raw = network.segmentation_head(x) if options.mode == "head" else network(x)
                    p = torch.sigmoid(raw[:, 0])
                    dice = 1-(2*(p*y[:, 0]).sum()+1)/(p.sum()+y[:, 0].sum()+1)
                    loss = (F.binary_cross_entropy_with_logits(raw[:, 0], y[:, 0], pos_weight=weight)
                            + dice + .25*F.binary_cross_entropy_with_logits(raw[:, 1], y[:, 1])
                            + .25*F.smooth_l1_loss(torch.tanh(raw[:, 2]), y[:, 2]))
                    if not torch.isfinite(loss):
                        raise RasterError("Building training produced a nonfinite objective.")
                    if update:
                        optimizer.zero_grad(set_to_none=True)
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_([p for p in network.parameters() if p.requires_grad], 1.)
                        optimizer.step()
                total += float(loss.detach()) * len(group)
                observations += len(group)
            return total/max(1, observations)
        best_loss = loss_for(validation)
        initial_loss = best_loss
        best_epoch = 0
        best = stage / "best.safetensors"

        def save_best():
            save_file({key: value.detach().cpu().contiguous() for key, value in network.state_dict().items()}, str(best))
        save_best()
        history = [{"epoch": 0, "training_loss": None, "validation_loss": best_loss}]
        rng = np.random.default_rng(options.seed)
        for epoch in range(1, options.epochs+1):
            ordered = [train[i] for i in rng.permutation(len(train))]
            training_loss = loss_for(ordered, update=True)
            validation_loss = loss_for(validation)
            history.append({"epoch": epoch, "training_loss": training_loss, "validation_loss": validation_loss})
            if validation_loss < best_loss:
                best_loss, best_epoch = validation_loss, epoch
                save_best()
            tick(.3 + .6*epoch/options.epochs)
        network.load_state_dict(load_file(str(best)), strict=True)
        manifest = {key: value for key, value in config.items() if key not in ("model_path", "id", "runtime")}
        manifest.update({"boundary_channel": 1, "distance_channel": 2, "output_channels": 3,
            "description": "Locally adapted building mask, boundary and distance heads; validation-selected checkpoint.",
            "training": {"dataset_fingerprint": dataset["fingerprint"], "initial_model_id": options.initial_model_id,
                "initial_checkpoint_sha256": file_sha256(checkpoint), "mode": options.mode, "seed": options.seed,
                "selection": "minimum validation multi-head loss; test rows never used"}})
        output = stage / "output"
        parity = export_model(network, output, manifest)
        report = {"dataset_fingerprint": dataset["fingerprint"], "counts": dataset["counts"], "regions": dataset["regions"],
            "parameters": options.model_dump(), "history": history, "best_epoch": best_epoch,
            "initial_validation_loss": initial_loss, "selected_validation_loss": best_loss,
            "validation_improved": best_epoch > 0, "test_used_for_training": False,
            "trainable_parameters": sum(p.numel() for p in network.parameters() if p.requires_grad),
            "torch_version": str(torch.__version__), "device": str(device), "onnx_parity": parity,
            "seconds": round(time.monotonic()-started, 3), "cache_bytes": bytes_cached,
            "model_sha256": file_sha256(output / "model.onnx"), "checkpoint_sha256": file_sha256(output / "model.safetensors"),
            "note": "Loss improvement is not test accuracy; frozen holdout comparison is required before qualification."}
        (output / "training.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        tick(1.)
        output.replace(destination)
    return report
