"""Compare pretrained external predictions on the original validation chips.

No test selection or external model execution occurs here. A real model receipt
is required for every validation image; partial smoke runs cannot be ranked.
"""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
import rasterio
from rasterio.features import shapes

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from imagery.store import file_sha256
from vision.building_dataset import load_dataset,canonical_sha
from vision.building_external import (CATALOG,read_prediction,polygon_fields,
    supported_instances,vector_consensus)
from vision.building_prediction import predict_image
from vision.building_ensemble_study import ensemble_fields
from vision.building_study import aggregate,balanced_validation_score,score_fields,_identity
from scripts.building_advanced_study import BASELINE,code_identity,select


def read_bundle(path,dataset):
    root=Path(path).resolve()
    m=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    name=m.get("model",{}).get("name")
    if (name not in CATALOG or m.get("sha256")!=canonical_sha({k:v for k,v in m.items() if k!="sha256"})
            or m.get("dataset_fingerprint")!=dataset["fingerprint"] or m.get("test_evaluated") is not False
            or m["model"].get("revision")!=CATALOG[name]["revision"]
            or m.get("settings",{}).get("split")!="validation"
            or m["settings"].get("checkpoint_loading")!="weights_only"):
        raise ValueError("Invalid external validation receipt.")
    rows=[r for r in dataset["samples"] if r["split"]=="validation"]
    entries=m.get("samples",[])
    if len(entries)!=len(rows) or len({r["id"] for r in entries})!=len(rows):
        raise ValueError("Incomplete external validation coverage; smoke runs are not rankable.")
    by_id={e["id"]:e for e in entries}
    result={}
    for i,r in enumerate(rows):
        e=by_id[r["id"]]
        expected=f"sample-{i:06d}"
        if e["folder"]!=expected:
            raise ValueError("Unexpected prediction folder.")
        field,ids,receipt=read_prediction(root/expected,r["paths"]["image"],name)
        if (receipt["sha256"]!=e["prediction_sha256"] or receipt["model"]!=m["model"]
                or receipt["settings"]!=m["settings"]):
            raise ValueError("External prediction receipt differs from its bundle.")
        result[r["id"]]=(field,ids,receipt)
    return name,m,result


def recipes(names):
    result=[{"name":"baseline","kind":"semantic",**BASELINE}]
    if "unibuild" in names:
        for weight in (0.,.25,.5,.75):
            for threshold in (.30,.35,.50,.65):
                for mode in ("adaptive","graph"):
                    result.append({"name":"unibuild","kind":"semantic","baseline_weight":weight,
                                   "probability_threshold":threshold,"instance_mode":mode,"seed_distance":6})
    vectors=[n for n in ("sampolybuild","pix2poly") if n in names]
    for name in vectors:
        result.append({"name":name,"kind":"native_instances","support":None})
        for semantic in ("baseline","unibuild") if "unibuild" in names else ("baseline",):
            for support in (.35,.50,.65):
                result.append({"name":name,"kind":"supported_instances","semantic":semantic,"support":support})
    if len(vectors)==2:
        for primary,secondary in (vectors,vectors[::-1]):
            for semantic in ("baseline","unibuild") if "unibuild" in names else ("baseline",):
                result.append({"name":"consensus","kind":"consensus","primary":primary,"secondary":secondary,
                               "semantic":semantic,"agreement":.5,"support":.5})
    return result


def evaluate(recipe,base,external,row):
    kind=recipe["kind"];diag=None
    if kind=="semantic":
        if recipe["name"]=="baseline":
            fields=base
        else:
            uni=external["unibuild"][0]
            fields=ensemble_fields(uni,base,recipe["baseline_weight"])
        metrics,ids=score_fields(fields,row,recipe["probability_threshold"],recipe["instance_mode"],recipe["seed_distance"])
    else:
        name=recipe["name"]
        if kind=="native_instances":
            ids=external[name][1]
            diag=external[name][2]["diagnostics"]
        else:
            semantic=base if recipe["semantic"]=="baseline" else external["unibuild"][0]
            if kind=="supported_instances":
                ids=supported_instances(external[name][1],semantic,threshold=recipe["support"])
            else:
                ids,diag=vector_consensus(external[recipe["primary"]][1],external[recipe["secondary"]][1],
                    semantic,agreement=recipe["agreement"],support=recipe["support"])
        fields=polygon_fields(ids,base["valid"])
        metrics,ids=score_fields(fields,row,.5,instance_override=ids)
    return metrics,ids,fields,diag


def export_native(path,row,ids,fields,recipe):
    """Native raster IDs and vector features; pixel-only CRS remains unspecified."""
    path.mkdir(parents=True,exist_ok=False)
    with rasterio.open(row["paths"]["image"]) as src:
        profile=src.profile.copy();transform=src.transform;crs=src.crs
    profile.update(driver="GTiff",count=1,dtype="int32",nodata=None,compress="deflate")
    with rasterio.open(path/"instances.tif","w",**profile) as dst:
        dst.write(ids.astype(np.int32),1)
    profile.update(dtype="uint8",nodata=255)
    with rasterio.open(path/"mask.tif","w",**profile) as dst:
        dst.write(np.where(fields["valid"],ids>0,255).astype(np.uint8),1)
    if recipe["kind"]=="semantic":
        profile.update(dtype="float32",nodata=-1)
        with rasterio.open(path/"probability.tif","w",**profile) as dst:
            dst.write(np.where(fields["valid"],fields["probability"],-1).astype(np.float32),1)
    features=[{"type":"Feature","properties":{"instance_id":int(v)},"geometry":g}
              for g,v in shapes(ids.astype(np.int32),mask=ids>0,transform=transform)]
    # GeoJSON RFC7946 expects longitude/latitude. Keep native coordinates in a
    # clearly marked custom feature bundle rather than claiming WGS84.
    (path/"footprints.json").write_text(json.dumps({"type":"FeatureCollection","features":features,
        "coordinate_space":"native_crs" if crs else "pixel_grid",
        "crs_wkt":crs.to_wkt() if crs else None},allow_nan=False),encoding="utf-8")


def public_aggregate(records,recipe):
    result=aggregate(records)
    if recipe["kind"]!="semantic":
        result.update({"brier_score":None,"ece":None,"ece_aggregation":None,
                       "probability_calibration":"not_applicable_binary_instance_support"})
    return result


def run(dataset_path,baseline,bundles,output,device):
    output=Path(output)
    if output.exists():
        raise ValueError("Choose a fresh comparison output.")
    if len(baseline)!=2 or baseline[0]==baseline[1] or not 1<=len(bundles)<=3:
        raise ValueError("Choose two baseline models and one to three external bundles.")
    dataset=load_dataset(dataset_path)
    rows=[r for r in dataset["samples"] if r["split"]=="validation"]
    ids=[_identity(m) for m in baseline]
    upstream={};fields={}
    for bundle in bundles:
        name,manifest,results=read_bundle(bundle,dataset)
        if name in upstream:
            raise ValueError("Duplicate external candidate.")
        upstream[name]=manifest;fields[name]=results
    grid=recipes(upstream)
    records=[[] for _ in grid];cached=[]
    code=canonical_sha({"core":code_identity(),"study":file_sha256(Path(__file__))})
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix=".external-study-",dir=output.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        for i,row in enumerate(rows):
            print(f"validation {i+1}/{len(rows)} {row['id']}",flush=True)
            base=ensemble_fields(*[predict_image(row["paths"]["image"],m,device=device,augmentation="flips") for m in baseline],.5)
            external={name:results[row["id"]] for name,results in fields.items()}
            if any(not np.array_equal(base["valid"],x[0]["valid"]) for x in external.values()):
                raise ValueError("Candidate and baseline source validity differ.")
            cached.append((row,base,external))
            for j,r in enumerate(grid):
                metrics,_,_,diag=evaluate(r,base,external,row)
                records[j].append({"sample_id":row["id"],"region":row["region"],"group":row["group"],
                    "metrics":metrics,"external_diagnostics":diag})
        winner=select(records,grid,0)
        folds=[];crossfit=[]
        for group in sorted({r["group"] for r in rows}):
            if len({r["group"] for r in rows})<2:
                break
            j=select(records,grid,0,excluded_group=group)
            folds.append({"group":group,"recipe":grid[j]})
            crossfit.extend(r for r in records[j] if r["group"]==group)
        for i,(row,base,external) in enumerate(cached):
            _,instance,field,_=evaluate(grid[winner],base,external,row)
            export_native(stage/"selected"/f"sample-{i:06d}",row,instance,field,grid[winner])
        if ([_identity(m) for m in baseline]!=ids or load_dataset(dataset_path,verify_pixels=False)["fingerprint"]!=dataset["fingerprint"]
                or canonical_sha({"core":code_identity(),"study":file_sha256(Path(__file__))})!=code):
            raise ValueError("Baseline, code or dataset changed during comparison.")
        # Receipt hashes bind the exact imported model settings/weights and predictions.
        for bundle in bundles:
            name,manifest,_=read_bundle(bundle,dataset)
            if manifest!=upstream[name]:
                raise ValueError("External prediction bundle changed during comparison.")
        plan={"dataset_fingerprint":dataset["fingerprint"],"baseline_models":ids,
              "external_receipts":{n:m["sha256"] for n,m in upstream.items()},"device":device,
              "code_sha256":code,"grid":grid,"candidate":grid[winner],"test_used_for_selection":False}
        plan["sha256"]=canonical_sha(plan)
        report={"selection":plan,"qualification":"validation_only","test_evaluated":False,
                "validation":[{"recipe":r,"aggregate":public_aggregate(v,r),"balanced":balanced_validation_score(v)}
                              for r,v in zip(grid,records)],
                "baseline_records":records[0],"candidate_records":records[winner],
                "crossfit":{"folds":folds,"aggregate":public_aggregate(crossfit,{"kind":"mixed"}) if crossfit else None},
                "note":"INRIA may overlap upstream training. Validation ranking is not independent generalization. Binary vector support is not probability calibration. No automatic promotion or holdout run."}
        for name,obj in (("selection.json",plan),("report.json",report)):
            (stage/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        stage.replace(output)
    print(json.dumps({"candidate":plan["candidate"],"qualification":report["qualification"]},indent=2))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--baseline",nargs=2,required=True)
    p.add_argument("--bundles",type=Path,nargs="+",required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    a=p.parse_args();run(a.dataset,a.baseline,a.bundles,a.output,a.device)
