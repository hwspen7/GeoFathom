"""Verify real CUDA execution, CPU/CUDA building fields and instance parity on a host."""
import argparse
import json
import subprocess
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def memory_snapshot():
    """Report device-wide memory snapshots; these are not per-process peak VRAM."""
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=uuid,name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10, check=True)
        return {"status": "measured", "device_rows": result.stdout.strip().splitlines(),
                "units": "MiB", "scope": "device-wide instantaneous allocation, not process peak"}
    except (OSError, subprocess.SubprocessError):
        return {"status": "unavailable"}


def partition_agreement(a, b):
    """Match partitions geometrically, without relying on arbitrary numeric IDs."""
    a, b = np.asarray(a, np.int64), np.asarray(b, np.int64)
    ca, cb = np.bincount(a.ravel()), np.bincount(b.ravel())
    pairs, intersections = np.unique(a.ravel()*(len(cb))+b.ravel(), return_counts=True)
    left, right = pairs//len(cb), pairs % len(cb)
    valid = (left > 0) & (right > 0)
    iou = intersections[valid]/(ca[left[valid]]+cb[right[valid]]-intersections[valid])
    matched = int(np.sum(iou >= .99))
    n_a, n_b = int(np.count_nonzero(ca[1:])), int(np.count_nonzero(cb[1:]))
    return {"matched_at_iou_0_99": matched, "cpu_instances": n_a, "cuda_instances": n_b,
            "passed": n_a == n_b == matched}


def accept(model_id, sample, repeats=5, *, output=None):
    if not 1 <= repeats <= 100:
        raise ValueError("Choose 1–100 inference repetitions.")
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
    import onnxruntime as ort
    from vision.semantic import _manifest
    from vision.building_prediction import predict_image
    from vision.building_instances import separate_components
    from imagery.store import file_sha256
    ort.disable_telemetry_events()
    providers = ort.get_available_providers()
    report = {"model_id": model_id, "available_providers": providers,
              "passed": False, "hardware_verified": False}
    if "CUDAExecutionProvider" not in providers:
        report.update({"status": "unavailable", "reason": "A real ONNX Runtime CUDA provider is required; CPU fallback cannot qualify this check."})
    else:
        before_memory = memory_snapshot()
        config = _manifest(model_id)
        report["model_sha256"] = file_sha256(config["model_path"])
        report["image_sha256"] = file_sha256(Path(sample))
        cpu = predict_image(sample, model_id, device="cpu")
        # The shared runtime rejects unexpected whole-provider CPU fallback.
        gpu = predict_image(sample, model_id, device="cuda")
        errors = {key: float(np.max(np.abs(cpu[key]-gpu[key]))) for key in cpu if key != "valid"}
        valid_equal = bool(np.array_equal(cpu["valid"], gpu["valid"]))
        common = cpu["valid"] & gpu["valid"]
        cpu_mask = common & (cpu["probability"] >= .5)
        gpu_mask = common & (gpu["probability"] >= .5)
        disagreement = float(np.mean(cpu_mask[common] != gpu_mask[common])) if common.any() else 1.
        a = separate_components(cpu_mask, np.maximum(cpu["probability"], 0), cpu.get("boundary"), cpu.get("distance"))
        b = separate_components(gpu_mask, np.maximum(gpu["probability"], 0), gpu.get("boundary"), gpu.get("distance"))
        partition = partition_agreement(a, b)
        # Profile the actual graph rather than trusting only an advertised provider name.
        options = ort.SessionOptions()
        options.enable_profiling = True
        options.profile_file_prefix = str(Path(output).with_suffix("")) if output else "building-cuda-profile"
        from core.cuda_environment import prepare_onnx_cuda
        prepare_onnx_cuda(ort)
        session = ort.InferenceSession(str(config["model_path"]), sess_options=options,
                                      providers=[("CUDAExecutionProvider", {"use_tf32": "0"}), "CPUExecutionProvider"])
        session.disable_fallback()
        if session.get_providers()[0] != "CUDAExecutionProvider":
            raise RuntimeError("Building graph did not create a CUDA-first session.")
        tensor = np.zeros((1, len(config["bands"]), config["tile_size"], config["tile_size"]), np.float32)
        session.run(None, {session.get_inputs()[0].name: tensor})
        durations = []
        for _ in range(repeats):
            started = time.perf_counter()
            session.run(None, {session.get_inputs()[0].name: tensor})
            durations.append(time.perf_counter()-started)
        profile = Path(session.end_profiling())
        events = json.loads(profile.read_text())
        counts = {}
        cpu_numeric_ops = []
        control = {"Shape", "Size", "Gather", "GatherElements", "Unsqueeze", "Squeeze", "Concat", "Cast", "Reshape", "Slice", "ConstantOfShape", "Range", "Expand", "If", "Loop"}
        for event in events:
            args = event.get("args", {})
            provider = args.get("provider")
            if event.get("cat") != "Node" or not provider:
                continue
            counts[provider] = counts.get(provider, 0)+1
            if provider == "CPUExecutionProvider" and args.get("op_name") not in control:
                cpu_numeric_ops.append(args.get("op_name", "unknown"))
        executed_cuda = counts.get("CUDAExecutionProvider", 0) > 0
        field_ok = all(error <= (.01 if key == "distance" else .002) for key, error in errors.items())
        report.update({"status": "completed", "hardware_verified": executed_cuda,
            "field_maximum_errors": errors, "valid_mask_equal": valid_equal,
            "binary_disagreement_fraction": disagreement, "cpu_instances": int(a.max()), "cuda_instances": int(b.max()),
            "instance_partition": partition, "memory_before": before_memory, "memory_after": memory_snapshot(),
            "executed_provider_node_events": counts, "cpu_numeric_operations": sorted(set(cpu_numeric_ops)),
            "allowed_cpu_control_operations": sorted(control), "profile": str(profile),
            "median_tile_seconds": float(np.median(durations)), "repeats": repeats,
            "passed": bool(executed_cuda and not cpu_numeric_ops and valid_equal and field_ok
                           and disagreement <= .001 and partition["passed"]),
            "note": "Each instance must match at IoU >= 0.99; labels need not have identical numeric IDs. CPU control/shape nodes are reported explicitly."})
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        raise SystemExit("Choose 1–100 inference repetitions.")
    result = accept(args.model, args.sample, args.repeats, output=args.output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
