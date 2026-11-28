"""Compare original and cached Pix2Poly native artifacts on identical chips."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision.building_dataset import load_dataset,canonical_sha
from vision.building_external import read_prediction


def compare(dataset_path,original,optimized):
    dataset=load_dataset(dataset_path)
    roots=[Path(original),Path(optimized)]
    manifests=[json.loads((r/"manifest.json").read_text(encoding="utf-8")) for r in roots]
    a,b=manifests
    for m in manifests:
        if (m.get("sha256")!=canonical_sha({k:v for k,v in m.items() if k!="sha256"})
                or m.get("dataset_fingerprint")!=dataset["fingerprint"] or m.get("test_evaluated") is not False
                or m.get("model",{}).get("name")!="pix2poly"):
            raise ValueError("Invalid Pix2Poly parity bundle.")
    def stable(m):
        s=m["settings"]
        return {k:v for k,v in s.items() if k not in ("code_sha256","encoder_cache","pix_adapter_sha256","pix_variant","sam_execution")}|{"pix_variant":s.get("pix_variant","inria")}
    if (a["model"]!=b["model"] or stable(a)!=stable(b)
            or a["settings"].get("encoder_cache",False) or not b["settings"].get("encoder_cache")
            or not a["samples"] or [r["id"] for r in a["samples"]]!=[r["id"] for r in b["samples"]]):
        raise ValueError("Parity requires identical model, inputs and settings except encoder caching.")
    rows={r["id"]:r for r in dataset["samples"] if r["split"]=="validation"}
    checks=[]
    for ea,eb in zip(a["samples"],b["samples"]):
        row=rows[ea["id"]]
        values=[]
        for root,e,m in zip(roots,(ea,eb),manifests):
            if not e["folder"].startswith("sample-") or not e["folder"][7:].isdigit():
                raise ValueError("Invalid parity folder.")
            _,ids,receipt=read_prediction(root/e["folder"],row["paths"]["image"],"pix2poly")
            if receipt["sha256"]!=e["prediction_sha256"] or receipt["model"]!=m["model"] or receipt["settings"]!=m["settings"]:
                raise ValueError("Parity receipt mismatch.")
            values.append((ids,receipt))
        x,y=values
        checks.append({"id":row["id"],"partition_exact":bool(np.array_equal(x[0],y[0])),
                       "polygon_exact":x[1]["polygon_sha256"]==y[1]["polygon_sha256"],
                       "pixel_difference":int(np.count_nonzero(x[0]!=y[0]))})
    passed=all(c["partition_exact"] and c["polygon_exact"] for c in checks)
    result={"passed":passed,"checks":checks,"original_seconds":a["seconds"],"optimized_seconds":b["seconds"],
            "speed_ratio":a["seconds"]/b["seconds"] if b["seconds"]>0 else None,
            "note":"Wall time includes loading and output; parity applies only to these chips and this runtime."}
    print(json.dumps(result,indent=2))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--original",type=Path,required=True)
    p.add_argument("--optimized",type=Path,required=True)
    a=p.parse_args()
    if not compare(a.dataset,a.original,a.optimized)["passed"]:
        raise SystemExit(1)
