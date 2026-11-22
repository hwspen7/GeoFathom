"""Operator-provisioned labeled dataset qualification; no training/accuracy fabrication."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def qualify(dataset,min_iou,min_coverage,min_class_pixels,confidence):
    import numpy as np
    from vision.evaluate import evaluate_model
    from vision.quality import metrics_from_matrix
    path=Path(dataset).resolve(strict=True)
    info=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(info,dict) or not isinstance(info.get("dataset_id"),str) or not info["dataset_id"].strip():
        raise ValueError("An independently labeled dataset identifier is required.")
    model=info["model_id"]
    if model=="gpu_acceptance":
        raise ValueError("Synthetic acceptance fixture cannot qualify satellite model accuracy.")
    scenes=info["scenes"]
    if not isinstance(scenes,list) or not 1<=len(scenes)<=1000:
        raise ValueError("Provide between 1 and 1000 distinct labeled scenes.")
    if not all(math.isfinite(v) and 0<=v<=1 for v in (min_iou,min_coverage,confidence)):
        raise ValueError("Accuracy, coverage and confidence thresholds must be between zero and one.")
    if type(min_class_pixels) is not int or min_class_pixels<1:
        raise ValueError("Every class requires positive label support.")
    records=[]
    seen=set()
    aggregate=None
    eligible=accepted=0
    for scene in scenes:
        def file(key):
            return (path.parent/scene[key]).resolve(strict=True)
        result=evaluate_model(file("image"),file("labels"),model,
            file("scl") if scene.get("scl") else None,confidence=confidence)
        identity=result["image_sha256"]
        if identity in seen:
            raise ValueError("Duplicate evaluation image detected.")
        seen.add(identity)
        if records and any(result[k]!=records[0][k] for k in ("model_sha256","manifest_sha256","device")):
            raise RuntimeError("Model or runtime changed during dataset qualification.")
        records.append(result)
        current=np.asarray(result["unfiltered"]["confusion_matrix"],np.int64)
        aggregate=current if aggregate is None else aggregate+current
        eligible+=result["eligible_pixels"]
        accepted+=result["valid_pixels"]
    classes=[item["name"] for item in records[0]["classes"]]
    metrics=metrics_from_matrix(aggregate,classes)
    coverage=accepted/eligible if eligible else 0
    iou=metrics["mean_iou_present_classes"]
    gates={"unfiltered_mean_iou":iou is not None and iou>=min_iou,
           "confidence_coverage":coverage>=min_coverage,
           "label_support_all_classes":all(c["support"]>=min_class_pixels for c in metrics["classes"])}
    return {"passed":all(gates.values()),"gates":gates,"dataset_id":info["dataset_id"],
        "model_id":model,"scene_count":len(records),"device":records[0]["device"],
        "coverage":coverage,"eligible_pixels":eligible,"accepted_pixels":accepted,
        "unfiltered":metrics,"scenes":records,
        "thresholds":{"min_iou":min_iou,"min_coverage":min_coverage,
                      "min_class_pixels":min_class_pixels,"confidence":confidence},
        "note":"Operator must independently establish label quality, representativeness and train/test separation."}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--min-iou",type=float,required=True)
    parser.add_argument("--min-coverage",type=float,required=True)
    parser.add_argument("--min-class-pixels",type=int,default=100)
    parser.add_argument("--confidence",type=float,default=.5)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=qualify(args.dataset,args.min_iou,args.min_coverage,args.min_class_pixels,args.confidence)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("Model qualification:", "PASS" if result["passed"] else "FAIL")
    if not result["passed"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
