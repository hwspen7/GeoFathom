"""Continuous real native CPU/CUDA spectral acceptance and memory-growth gate.

Short CI runs exercise the gate; use --seconds 86400 on the target machine
for a separate 24-hour qualification. No extrapolation from the short run.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path
import sys
import time

import numpy as np
import psutil

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from geometry.spectral import normalized_difference,paired_change
from geometry.topology import native_available

def run(seconds=10,min_rate=1_000_000,max_growth_mb=128,device="cpu",
        max_device_growth_mb=256):
    if not 5<=seconds<=86400 or min_rate<=0 or max_growth_mb<=0 or max_device_growth_mb<=0:
        raise ValueError("Invalid acceptance thresholds.")
    os.environ["GEOFATHOM_SPECTRAL_DEVICE"]=device
    if not native_available():
        raise RuntimeError("Native library is required for soak acceptance.")
    shape=(512,512)
    a=np.full(shape,200,np.float32);b=np.full(shape,50,np.float32)
    valid=np.ones(shape,np.uint8)
    process=psutil.Process()
    expected="cuda-spectral" if device=="cuda" else "cpp-spectral"
    def iteration():
        values,mask,engine=normalized_difference(a,b,valid)
        if engine!=expected or not mask.all() or not np.allclose(values,.6):
            raise RuntimeError("Native spectral invariant failed.")
        labels,both,_,_=paired_change((a,b),valid,(b,a),valid,.25)
        if not both.all() or not np.all(labels==2):
            raise RuntimeError("Native change classification invariant failed.")
    for _ in range(20):iteration()
    initial=process.memory_info().rss
    peak=initial
    # Native allocated bytes are per runtime; nvidia-smi is device-wide.
    # Unrelated GPU activity can invalidate the device-wide comparison.
    def gpu_memory():
        from geometry.cuda import stats
        device_id=int(os.getenv("GEOFATHOM_GPU_MONITOR_INDEX","0"))
        used=subprocess.run(["nvidia-smi","-i",str(device_id),
            "--query-gpu=memory.used","--format=csv,noheader,nounits"],
            capture_output=True,text=True,timeout=8,check=True).stdout.strip()
        return stats()["allocated_bytes"],int(used)
    native_initial,device_initial=gpu_memory() if device=="cuda" else (0,0)
    native_peak,device_peak=native_initial,device_initial
    samples=1 if device=="cuda" else 0
    started=time.perf_counter()
    next_sample=started+2
    iterations=0
    while time.perf_counter()-started<seconds:
        iteration()
        iterations+=1
        peak=max(peak,process.memory_info().rss)
        if device=="cuda" and time.perf_counter()>=next_sample:
            native_used,device_used=gpu_memory()
            native_peak=max(native_peak,native_used)
            device_peak=max(device_peak,device_used)
            samples+=1
            next_sample=time.perf_counter()+2
    if device=="cuda":
        native_used,device_used=gpu_memory()
        native_peak=max(native_peak,native_used)
        device_peak=max(device_peak,device_used)
        samples+=1
    elapsed=time.perf_counter()-started
    rate=iterations*shape[0]*shape[1]*3/elapsed
    growth=(peak-initial)/1024**2
    result={"device":device,"seconds":elapsed,"iterations":iterations,
            "pixels_per_second":round(rate),"peak_rss_growth_mb":round(growth,2),
            "min_pixels_per_second":min_rate,"max_rss_growth_mb":max_growth_mb,
            "passed":rate>=min_rate and growth<=max_growth_mb}
    if device=="cuda":
        native_growth=(native_peak-native_initial)/1024**2
        device_growth=device_peak-device_initial
        result.update(native_cuda_peak_growth_mb=round(native_growth,2),
            device_wide_peak_growth_mb=device_growth,gpu_memory_samples=samples,
            max_device_growth_mb=max_device_growth_mb,
            gpu_memory_scope="Native runtime allocation plus sampled total device memory")
        result["passed"] = result["passed"] and native_growth<=max_device_growth_mb and device_growth<=max_device_growth_mb
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds",type=int,default=10)
    parser.add_argument("--min-rate",type=int,default=1_000_000)
    parser.add_argument("--max-growth-mb",type=int,default=128)
    parser.add_argument("--device",choices=["cpu","cuda"],default="cpu")
    parser.add_argument("--max-device-growth-mb",type=int,default=256)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=run(args.seconds,args.min_rate,args.max_growth_mb,args.device,args.max_device_growth_mb)
    out=json.dumps(result,indent=2)
    if args.output:args.output.write_text(out,encoding="utf-8")
    print(out)
    if not result["passed"]:raise SystemExit(1)

if __name__=="__main__":
    main()
