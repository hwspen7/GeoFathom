"""Evaluate a local ONNX semantic model against real georeferenced labels.

This operator-only tool reads full-resolution GeoTIFF bands and annotations
in bounded tiles. A labeled dataset is required; no synthetic scores are
reported as real-world model accuracy.
"""
import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from imagery.raster import RasterError,_check
from imagery.store import file_sha256
from vision.quality import (confusion_matrix,metrics_from_matrix,
                            sentinel2_clear_mask)
from vision.semantic import _manifest,_predict_tile
from vision.tiled import TilePlan,_tile_bands


def evaluate_model(image,ground_truth,model_id,scl=None,
                   max_pixels=16_777_216,memory_mb=64,
                   confidence=.5):
    if not 0<=confidence<=1:
        raise RasterError("Invalid evaluation confidence threshold.")
    config=_manifest(model_id)
    device=os.getenv("GEOFATHOM_VISION_DEVICE","cpu").lower()
    if device not in ("cpu","cuda"):
        raise RasterError("Unsupported model evaluation device.")
    started=time.monotonic()
    image=Path(image)
    ground_truth=Path(ground_truth)
    with rasterio.open(image) as scene,rasterio.open(ground_truth) as labels:
        _check(scene)
        _check(labels)
        if max(config["bands"])>scene.count:
            raise RasterError("Image is missing required model bands.")
        plan=TilePlan(scene.width,scene.height,config["tile_size"],
                      max_pixels,memory_mb)
        classes=config["classes"]
        matrix=np.zeros((len(classes),len(classes)),dtype=np.int64)
        ignored=0
        mean=np.asarray(config["mean"],dtype=np.float32)[:,None,None]
        std=np.asarray(config["std"],dtype=np.float32)[:,None,None]
        with WarpedVRT(labels,crs=scene.crs,transform=scene.transform,
                       width=scene.width,height=scene.height,
                       resampling=Resampling.nearest) as aligned:
            from contextlib import ExitStack
            with ExitStack() as optional:
                scl_aligned=None
                if scl is not None:
                    source=optional.enter_context(rasterio.open(Path(scl)))
                    _check(source)
                    scl_aligned=optional.enter_context(WarpedVRT(
                        source,crs=scene.crs,transform=scene.transform,
                        width=scene.width,height=scene.height,
                        resampling=Resampling.nearest))
                for window in plan.windows():
                    raw,valid=_tile_bands(scene,config["bands"],window)
                    truth=aligned.read(1,window=window,masked=True)
                    rows,cols=int(window.height),int(window.width)
                    normalized=(np.nan_to_num(raw,nan=0,posinf=0,neginf=0) /
                                config["input_scale"]-mean)/std
                    tensor=np.zeros((1,len(config["bands"]),plan.tile_size,
                                     plan.tile_size),dtype=np.float32)
                    tensor[0,:,:rows,:cols]=normalized
                    predicted,probability=_predict_tile(tensor,config,device)
                    accepted=(valid & ~np.ma.getmaskarray(truth) &
                              (probability[:rows,:cols]>=confidence))
                    if scl_aligned is not None:
                        quality=scl_aligned.read(1,window=window,masked=True)
                        accepted&=(~np.ma.getmaskarray(quality) &
                                   sentinel2_clear_mask(quality.filled(0)))
                    ignored+=int(accepted.size-accepted.sum())
                    matrix+=confusion_matrix(np.asarray(truth.data),
                        predicted[:rows,:cols],len(classes),accepted)
    result=metrics_from_matrix(matrix,classes)
    result.update({
        "model_id":model_id,"device":device,"confidence_min":confidence,
        "image_sha256":file_sha256(image),
        "labels_sha256":file_sha256(ground_truth),
        "model_sha256":file_sha256(config["model_path"]),
        "scl_sha256":file_sha256(Path(scl)) if scl else None,
        "ignored_pixels":ignored,
        "image_grid":[plan.width,plan.height],
        "seconds":round(time.monotonic()-started,4),
        "note":"Quantitative accuracy on the provided labels only. "
               "Train/test separation, independent annotation quality and "
               "confidence calibration must be checked separately.",
    })
    return result


def main():
    parser=argparse.ArgumentParser(description="Evaluate ONNX model on labeled imagery")
    parser.add_argument("--image",type=Path,required=True)
    parser.add_argument("--labels",type=Path,required=True)
    parser.add_argument("--model",required=True)
    parser.add_argument("--scl",type=Path)
    parser.add_argument("--confidence",type=float,default=.5)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=evaluate_model(args.image,args.labels,args.model,args.scl,
                          confidence=args.confidence)
    rendered=json.dumps(result,indent=2)
    if args.output:
        args.output.write_text(rendered,encoding="utf-8")
    print(rendered)


if __name__=="__main__":
    main()
