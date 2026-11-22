"""Real local RTX 4070 Ti SUPER/other-CUDA acceptance with ONNX weights.

Requires actual CUDA runtime, a configured model and NVIDIA driver. No
mocked outputs or CI-only GPU claims. Measures process RSS and total
device memory used; nvidia-smi sees all processes on that GPU, not only ours.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from threading import Event,Thread
import time

import numpy as np
import psutil

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision.semantic import _manifest,_predict_tile


def gpu_stats():
    result=subprocess.run(["nvidia-smi",
        "-i",os.getenv("GEOFATHOM_GPU_MONITOR_INDEX","0"),
        "--query-gpu=name,memory.total,memory.used",
        "--format=csv,noheader,nounits"],
        capture_output=True,text=True,timeout=8,check=True)
    line=result.stdout.splitlines()
    if not line:
        raise RuntimeError("NVIDIA GPU was not detected.")
    parts=[part.strip() for part in line[0].split(",")]
    if len(parts)!=3:
        raise RuntimeError("Unexpected nvidia-smi format.")
    return {"name":parts[0],"total_mb":int(parts[1]),"used_mb":int(parts[2])}


def acceptance(model_id,runs=50,warmup=5):
    if not 10<=runs<=500 or not 1<=warmup<=50:
        raise ValueError("Unsafe inference benchmark iteration count.")
    os.environ["GEOFATHOM_VISION_DEVICE"]="cuda"
    config=_manifest(model_id)
    gpu=gpu_stats()
    expected=os.getenv("GEOFATHOM_GPU_EXPECTED_NAME","4070 Ti SUPER")
    if expected and expected.lower() not in gpu["name"].lower():
        raise RuntimeError("Detected GPU differs from the declared acceptance hardware.")
    import onnxruntime as ort
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError("ONNX Runtime CUDAExecutionProvider is unavailable.")
    size=config["tile_size"]
    tensor=np.zeros((1,len(config["bands"]),size,size),dtype=np.float32)
    for _ in range(warmup):
        _predict_tile(tensor,config,"cuda")
    stop=Event()
    samples=[]
    def watch():
        while not stop.wait(.15):
            try:samples.append(gpu_stats()["used_mb"])
            except (OSError,RuntimeError,subprocess.SubprocessError):pass
    thread=Thread(target=watch,daemon=True)
    thread.start()
    times=[]
    rss=[]
    wall_start=time.perf_counter()
    proc=psutil.Process()
    try:
        for _ in range(runs):
            start=time.perf_counter()
            labels,conf=_predict_tile(tensor,config,"cuda")
            times.append((time.perf_counter()-start)*1000)
            rss.append(proc.memory_info().rss/(1024*1024))
            if labels.shape!=(size,size) or not np.isfinite(conf).all():
                raise RuntimeError("GPU inference produced an invalid tensor.")
    finally:
        wall_elapsed=time.perf_counter()-wall_start
        stop.set()
        thread.join(2)
    end=gpu_stats()
    return {
        "model_id":model_id,"gpu":gpu["name"],
        "gpu_total_mb":gpu["total_mb"],
        "gpu_before_mb":gpu["used_mb"],
        "gpu_peak_observed_mb":max(samples+[end["used_mb"]]),
        "gpu_after_mb":end["used_mb"],
        "cpu_peak_rss_mb":round(max(rss),2),
        "runs":runs,"warmup":warmup,
        "median_latency_ms":round(statistics.median(times),3),
        "p95_latency_ms":round(float(np.percentile(times,95)),3),
        "throughput_tiles_per_second":round(runs/wall_elapsed,2),
        "reciprocal_median_tiles_per_second":round(1000/statistics.median(times),2),
        "io_binding_enabled":os.getenv("GEOFATHOM_VISION_IO_BINDING")=="1",
        "note":"Measured on the local GPU with actual ONNX weights. "
               "Device memory includes unrelated GPU processes; sampling "
               "can miss momentary allocation peaks. No model accuracy "
               "can be inferred without an independent labeled dataset.",
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model",required=True)
    parser.add_argument("--runs",type=int,default=50)
    parser.add_argument("--warmup",type=int,default=5)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=json.dumps(acceptance(args.model,args.runs,args.warmup),indent=2)
    if args.output:
        args.output.write_text(result,encoding="utf-8")
    print(result)


if __name__=="__main__":
    main()
