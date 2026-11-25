"""Opt-in reproducible native-vs-NumPy microbenchmark; no speedup claims.

Usage: python benchmarks/native_pipeline.py --size 4096 --segments 100000
The measured times are local hardware observations, not CI pass/fail gates.
"""
import argparse
import gc
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import geometry.spectral as spectral
from geometry.spatial import SegmentIndex


def measure(action, repeats):
    values=[]
    for _ in range(repeats):
        gc.collect()
        start=time.perf_counter()
        action()
        values.append(time.perf_counter()-start)
    return {"median_seconds":round(statistics.median(values),6),
            "min_seconds":round(min(values),6),
            "max_seconds":round(max(values),6)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--size",type=int,default=2048)
    parser.add_argument("--segments",type=int,default=100000)
    parser.add_argument("--queries",type=int,default=10000)
    parser.add_argument("--repeats",type=int,default=3)
    args=parser.parse_args()
    if (not 128<=args.size<=4096 or not 1<=args.segments<=1000000
            or not 1<=args.queries<=100000 or not 1<=args.repeats<=10):
        parser.error("Requested benchmark resources exceed local safety limits.")
    rng=np.random.default_rng(416)
    a=rng.uniform(1,2000,(args.size,args.size)).astype(np.float32)
    b=rng.uniform(1,2000,(args.size,args.size)).astype(np.float32)
    valid=np.ones(a.shape,dtype=np.uint8)
    observed=spectral.normalized_difference(a,b,valid)
    actual=observed[-1]
    native=measure(lambda:spectral.normalized_difference(a,b,valid),args.repeats)
    old=spectral._native
    try:
        spectral._native=lambda:None
        fallback=measure(lambda:spectral.normalized_difference(a,b,valid),
                         args.repeats)
    finally:
        spectral._native=old
    coords=[((float(i*3),0.),(float(i*3),100.)) for i in range(args.segments)]
    queries=np.column_stack((
        rng.integers(0,args.segments,args.queries)*3+.1,
        rng.uniform(0,100,args.queries),
    ))
    with SegmentIndex(coords) as index:
        index_engine=index.engine
        indexed=measure(lambda:index.query_many(queries,1.),
                        args.repeats)
    output={
        "raster_shape":[args.size,args.size],"pixel_count":args.size**2,
        "spectral_engine":actual,"native_seconds":native,
        "numpy_seconds":fallback,
        "native_pixels_per_second":round(args.size**2/native["median_seconds"]),
        "numpy_pixels_per_second":round(args.size**2/fallback["median_seconds"]),
        "spatial_engine":index_engine,"indexed_segments":args.segments,
        "queries_per_batch":args.queries,"spatial_batch_seconds":indexed,
        "note":"Warm-cache microbenchmark; excludes GDAL disk IO, GPU transfers and polygonization.",
    }
    print(json.dumps(output,indent=2))


if __name__=="__main__":
    main()
