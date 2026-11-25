"""Real 100-million-cell tiled DEM scientific scaling gate.

The test uses a projected synthetic analytic plane, not a claim of survey
accuracy. Measure wall time, sampled RSS and native-resolution invariants.
Run independently of the regular unit suite to avoid duplicating large tests.
"""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import tempfile
from threading import Event,Thread
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import numpy as np
import psutil
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
from shapely.geometry import box,mapping
from terrain import compute_resources as cr
from terrain.tiled import analyze_area_tiled


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    rows=cols=10001
    process=psutil.Process()
    with tempfile.TemporaryDirectory(prefix="terrain-scale-") as work:
        path=Path(work)/"analytic.tif"
        affine=from_origin(500000,4500000,10,10)
        with rasterio.Env(GDAL_CACHEMAX=64*1024**2):
            with rasterio.open(path,"w",driver="GTiff",width=cols,height=rows,count=1,
                dtype="float32",crs="EPSG:32617",transform=affine,nodata=-9999,
                tiled=True,blockxsize=256,blockysize=256,compress="deflate") as dst:
                for top in range(0,rows,256):
                    h=min(256,rows-top)
                    for left in range(0,cols,256):
                        w=min(256,cols-left)
                        plane=np.broadcast_to(np.arange(left,left+w,dtype=np.float32),(h,w)).copy()
                        dst.write(plane,1,window=Window(left,top,w,h))
            # Freeze a reproducible bounded tile policy, not an artificial
            # host resource claim. Native source reads retain their full grid.
            host=cr.detect_host()
            limits=cr.resolve_limits(cr.ComputePolicy(mode="manual",concurrent_tasks=1,tile_size=512,backend="cpu"),host)
            if not limits.tile_size or limits.slope_cells<rows*cols:
                raise RuntimeError("Host cannot admit the required 100-million-cell scientific benchmark.")
            token=cr._active.set(limits)
            start_rss=process.memory_info().rss
            peak=[start_rss]
            stopped=Event()
            def observe():
                while not stopped.wait(.02):
                    peak[0]=max(peak[0],process.memory_info().rss)
            sampler=Thread(target=observe,daemon=True)
            start=time.monotonic()
            sampler.start()
            try:
                with rasterio.open(path) as src:
                    result=analyze_area_tiled(src,mapping(box(*src.bounds)),Window(0,0,cols,rows),
                        checkpoint_root=Path(work)/"checkpoints")
            finally:
                stopped.set();sampler.join()
                peak[0]=max(peak[0],process.memory_info().rss)
                cr._active.reset(token)
            elapsed=time.monotonic()-start
            observed=peak[0]-start_rss
            reference=math.degrees(math.atan(.1))
            checks={
                "source_pixels":result["valid_pixels"]==rows*cols,
                "complete_halos":result["gradient_pixels"]==(rows-2)*(cols-2),
                "slope_accuracy":abs(result["mean_slope_deg"]-reference)<.001,
                "elevation_mean":abs(result["elevation_mean_m"]-(cols-1)/2)<1e-8,
                "tile_count":result["tiles_processed"]==math.ceil(rows/limits.tile_size)*math.ceil(cols/limits.tile_size),
                "sampled_rss_growth_under_512_mib":observed<=512*1024**2,
            }
            record={"cells":rows*cols,"tile_size":limits.tile_size,"wall_seconds":elapsed,
                "sampled_peak_rss_bytes":peak[0],"baseline_rss_bytes":start_rss,
                "sampled_rss_growth_bytes":observed,"reference_slope_deg":reference,
                "result_slope_deg":result["mean_slope_deg"],"checks":checks,"passed":all(checks.values())}
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(record,indent=2),encoding="utf-8")
            print(json.dumps(record,indent=2),flush=True)
            return 0 if record["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
