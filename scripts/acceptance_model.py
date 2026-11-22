"""Generate and strictly verify a synthetic ONNX CUDA acceptance model.

This is a numerical/transport fixture, not a trained satellite classifier.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create(directory):
    import numpy as np
    import onnx
    from onnx import helper, TensorProto, numpy_helper

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    size = 512
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, ["N", 3, size, size])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, ["N", 2, size, size])
    weights = np.empty((2, 3, 1, 1), np.float32)
    weights[0].fill(-1/3)
    weights[1].fill(1/3)
    graph = helper.make_graph(
        [helper.make_node("Conv", ["input", "weights"], ["output"])],
        "GeoFathomAcceptance", [x], [y], [numpy_helper.from_array(weights, "weights")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)
    onnx.checker.check_model(model)
    onnx.save(model, str(directory / "gpu_acceptance.onnx"))
    manifest = {"description": "Synthetic GPU numerical acceptance fixture",
                "classes": ["background", "target"], "bands": [1, 2, 3],
                "tile_size": size, "max_batch": 4, "input_scale": 255, "halo": 0}
    (directory / "gpu_acceptance.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def verify(directory, output):
    import numpy as np
    import onnxruntime as ort
    from core.cuda_environment import prepare_onnx_cuda
    from vision.semantic import _manifest, _predict_batch

    directory = create(directory)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["GEOFATHOM_VISION_MODELS_DIR"] = str(directory)
    os.environ["GEOFATHOM_VISION_DEVICE_POSTPROCESS"] = "1"
    os.environ["GEOFATHOM_VISION_IO_BINDING"] = "1"
    prepare_onnx_cuda(ort)
    config = _manifest("gpu_acceptance")
    options = ort.SessionOptions()
    options.enable_profiling = True
    options.profile_file_prefix = str(output.parent / "ort-cuda-profile")
    options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
    session = ort.InferenceSession(str(config["model_path"]), sess_options=options,
                                   providers=["CUDAExecutionProvider"])
    session.disable_fallback()
    if session.get_providers()[0] != "CUDAExecutionProvider":
        raise RuntimeError("Strict CUDA provider selection failed.")
    x = np.ones((4, 3, 512, 512), dtype=np.float32)
    x[1::2] *= -1
    for _ in range(20):
        raw = session.run(None, {"input": x})[0]
        np.testing.assert_allclose(raw[:, 1], x[:, 0], atol=1e-6, rtol=0)
    profile = Path(session.end_profiling())
    events = json.loads(profile.read_text(encoding="utf-8"))
    providers = {e["args"]["provider"] for e in events if e.get("cat") == "Node"
                 and "provider" in e.get("args", {})}
    if providers != {"CUDAExecutionProvider"}:
        raise RuntimeError(f"Unexpected actual operator providers: {providers}")
    cpu, cpu_conf = _predict_batch(x, config, "cpu")
    gpu, gpu_conf = _predict_batch(x, config, "cuda")
    expected = np.broadcast_to(np.array([1, 0, 1, 0], np.uint8)[:, None, None], cpu.shape)
    np.testing.assert_array_equal(cpu, expected)
    np.testing.assert_array_equal(gpu, expected)
    np.testing.assert_allclose(cpu_conf, gpu_conf, atol=1e-6, rtol=0)
    np.testing.assert_allclose(gpu_conf, 1/(1+np.exp(-2)), atol=1e-6, rtol=0)
    result = {"passed": True, "providers": sorted(providers), "batch": 4,
              "profile": str(profile), "max_confidence_error": float(np.max(np.abs(cpu_conf-gpu_conf))),
              "synthetic_fixture": True}
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        verify(args.directory, args.output)
    else:
        print(create(args.directory))


if __name__ == "__main__":
    main()
