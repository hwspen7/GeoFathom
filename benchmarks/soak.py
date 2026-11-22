"""Continuous real native CPU/CUDA spectral acceptance and memory-growth gate.

Short CI runs exercise the gate; use --seconds 600 for the final
project-level qualification. Longer production runs are optional.
No extrapolation from the short run.
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
    # Alternate a full tile and odd/small shapes to exercise allocation
    # reuse, edge blocks and array boundaries. Precompute expected masks and
    # values using an independent float64 reference outside the timed loop.
    rng=np.random.default_rng(3567)
    fixtures=[]
    for shape in ((512,512),(257,259),(511,513),(63,65)):
        a=rng.uniform(1,1000,shape).astype(np.float32)
        b=rng.uniform(1,1000,shape).astype(np.float32)
        valid=rng.integers(0,2,shape,dtype=np.uint8)
        a.flat[:4]=[0,np.nan,np.inf,np.finfo(np.float32).max]
        b.flat[:4]=[0,1,1,np.finfo(np.float32).max]
        valid.flat[:4]=1
        x,y=a.astype(np.float64),b.astype(np.float64)
        with np.errstate(invalid="ignore"):
            denominator=x+y
            mask=(valid!=0)&np.isfinite(x)&np.isfinite(y)&(np.abs(denominator)>1e-9)
            index=np.zeros(shape,np.float32)
            np.divide(x-y,denominator,out=index,where=mask,casting="unsafe")
        np.clip(index,-1,1,out=index)
        delta=-2*index.astype(np.float64)
        labels=np.zeros(shape,np.uint8)
        labels[mask&(delta>=.25)]=1
        labels[mask&(delta<=-.25)]=2
        fixtures.append((a,b,valid,index,mask,labels))
    process=psutil.Process()
    expected="cuda-spectral" if device=="cuda" else "cpp-spectral"
    def iteration(i):
        a,b,valid,index,expected_mask,expected_labels=fixtures[i%len(fixtures)]
        values,mask,engine=normalized_difference(a,b,valid)
        if engine!=expected or not np.array_equal(mask,expected_mask) or not np.allclose(values,index,rtol=0,atol=1e-6):
            raise RuntimeError("Native spectral invariant failed.")
        labels,both,paired_engine,_=paired_change((a,b),valid,(b,a),valid,.25)
        expected_paired="cuda-spectral-fused" if device=="cuda" else expected
        if paired_engine!=expected_paired or not np.array_equal(both,expected_mask) or not np.array_equal(labels,expected_labels):
            raise RuntimeError("Native change classification invariant failed.")
        return a.size*3
    for i in range(20):iteration(i)
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
    processed_pixels=0
    while time.perf_counter()-started<seconds:
        processed_pixels+=iteration(iterations)
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
    rate=processed_pixels/elapsed
    growth=(peak-initial)/1024**2
    result={"device":device,"seconds":elapsed,"iterations":iterations,
            "pixels_per_second":round(rate),"processed_pixels":processed_pixels,
            "fixture_shapes":[list(f[0].shape) for f in fixtures],
            "pixel_tolerance":1e-6,"peak_rss_growth_mb":round(growth,2),
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
