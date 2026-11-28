"""Compare multiple checkpoints of the same architecture without name collisions.

Validation-only. This is a domain-shift diagnostic, not an independent-test
qualification or proof of training disjointness. No upstream models execute here.
"""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from imagery.store import file_sha256
from vision.building_dataset import load_dataset,canonical_sha
from vision.building_external import polygon_fields,additive_instances
from vision.building_study import aggregate,balanced_validation_score,score_fields,_identity
from vision.building_prediction import predict_image
from vision.building_ensemble_study import ensemble_fields
from scripts.building_advanced_study import BASELINE,code_identity,select
from scripts.building_external_study import read_bundle,export_native,public_aggregate


def recipe_grid(names):
    grid=[{"name":"baseline","kind":"semantic",**BASELINE}]
    for name in names:
        grid.append({"name":name,"kind":"native_instances"})
        for secondary in ("baseline",*[n for n in names if n!=name]):
            for support in (.5,.7):
                grid.append({"name":name,"kind":"additive","secondary":secondary,"support":support})
    return grid


def evaluate(recipe,row,base,base_ids,external):
    kind=recipe["kind"]
    if kind=="semantic":
        metrics,ids=score_fields(base,row,BASELINE["probability_threshold"],BASELINE["instance_mode"],BASELINE["seed_distance"])
        return metrics,ids,base,None
    ids=external[recipe["name"]][1];diag=None
    if kind=="additive":
        secondary=base_ids if recipe["secondary"]=="baseline" else external[recipe["secondary"]][1]
        ids,diag=additive_instances(ids,secondary,base,support=recipe["support"])
    fields=polygon_fields(ids,base["valid"])
    metrics,ids=score_fields(fields,row,.5,instance_override=ids)
    metrics["probability_calibration"]="not_applicable_binary_instance_support"
    return metrics,ids,fields,diag


def explain(records,grid,winner):
    base=aggregate(records[0]);result=[]
    for i,(r,rows) in enumerate(zip(grid,records)):
        a=public_aggregate(rows,r)
        b=balanced_validation_score(rows)
        pixel=a["classes"][1]["f1"]-base["classes"][1]["f1"]
        obj=a["objects_75"]["f1"]-base["objects_75"]["f1"]
        reasons=[]
        if pixel<-.01-1e-12: reasons.append("pixel_f1_loss_exceeds_0.01")
        if obj<-.01-1e-12: reasons.append("object75_loss_exceeds_0.01")
        if not reasons and i!=winner:
            reasons.append("lower_rank_or_tie")
        result.append({"recipe":r,"aggregate":a,"balanced":b,"eligible":pixel>=-.01-1e-12 and obj>=-.01-1e-12,
                       "selected":i==winner,"reasons":reasons,"pixel_f1_delta":pixel,"object75_delta":obj,
                       "region_scores":{region:public_aggregate([v for v in rows if v["region"]==region],r)
                                        for region in sorted({v["region"] for v in rows})}})
    return result


def run(dataset_path,baseline,bundles,output,device):
    output=Path(output)
    if output.exists() or not 1<=len(bundles)<=5 or len(baseline)!=2 or len(set(baseline))!=2:
        raise ValueError("Use a new output, two baseline models, and one to five named bundles.")
    dataset=load_dataset(dataset_path)
    rows=[r for r in dataset["samples"] if r["split"]=="validation"]
    import rasterio
    pixels=0
    for row in rows:
        with rasterio.open(row["paths"]["image"]) as src:
            pixels+=src.width*src.height
    if pixels*(28+12*len(bundles))>768*1024**2:
        raise ValueError("Retained native grids exceed the explicit comparison allowance.")
    identity=[_identity(m) for m in baseline]
    entries={};fields={};paths={};seen=set()
    for item in bundles:
        alias,sep,path=item.partition("=")
        if not sep or not alias or alias=="baseline" or alias in entries or not alias.replace("-","").isalnum():
            raise ValueError("Use unique named bundles: alias=directory.")
        name,m,data=read_bundle(path,dataset)
        if name not in ("pix2poly","sampolybuild") or m["sha256"] in seen:
            raise ValueError("Use distinct native instance prediction bundles.")
        seen.add(m["sha256"]);entries[alias]=m;fields[alias]=data;paths[alias]=path
    grid=recipe_grid(list(entries))
    records=[[] for _ in grid];cache=[]
    code=canonical_sha({"core":code_identity(),"transfer":file_sha256(Path(__file__)),
                        "external":file_sha256(Path(__file__).with_name("building_external_study.py"))})
    for i,row in enumerate(rows):
        print(f"validation {i+1}/{len(rows)} {row['id']}",flush=True)
        base=ensemble_fields(*[predict_image(row["paths"]["image"],m,device=device,augmentation="flips") for m in baseline],.5)
        external={name:results[row["id"]] for name,results in fields.items()}
        if any(not np.array_equal(base["valid"],v[0]["valid"]) for v in external.values()):
            raise ValueError("Native validity differs.")
        _,base_ids=score_fields(base,row,.35,"adaptive",6)
        cache.append((row,base,base_ids,external))
        for j,r in enumerate(grid):
            metrics,_,_,diag=evaluate(r,row,base,base_ids,external)
            records[j].append({"sample_id":row["id"],"region":row["region"],"group":row["group"],
                               "metrics":metrics,"additions":diag})
    winner=select(records,grid,0)
    ranking=explain(records,grid,winner)
    groups=sorted({r["group"] for r in rows});folds=[];crossfit=[]
    if len(groups)>1:
        for group in groups:
            j=select(records,grid,0,excluded_group=group)
            folds.append({"group":group,"recipe":grid[j]})
            crossfit.extend(r for r in records[j] if r["group"]==group)
    for alias,path in paths.items():
        if read_bundle(path,dataset)[1]!=entries[alias]:
            raise ValueError("External prediction changed during comparison.")
    if ([_identity(m) for m in baseline]!=identity or load_dataset(dataset_path,verify_pixels=False)["fingerprint"]!=dataset["fingerprint"]
            or canonical_sha({"core":code_identity(),"transfer":file_sha256(Path(__file__)),
                "external":file_sha256(Path(__file__).with_name("building_external_study.py"))})!=code):
        raise ValueError("Comparison inputs changed.")
    plan={"dataset_fingerprint":dataset["fingerprint"],"code_sha256":code,"baseline_models":identity,
          "device":device,"candidate":grid[winner],"grid":grid,"external_receipts":{a:m["sha256"] for a,m in entries.items()},
          "test_used_for_selection":False}
    plan["sha256"]=canonical_sha(plan)
    report={"selection":plan,"qualification":"validation_only","test_evaluated":False,
            "validation":ranking,"baseline_records":records[0],"candidate_records":records[winner],
            "crossfit":{"folds":folds,"aggregate":public_aggregate(crossfit,{"kind":"mixed"}) if crossfit else None},
            "note":"A checkpoint name is not a training-source audit. INRIA validation is not independent for INRIA-trained models. Additive fusion never deletes primary objects."}
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix=".transfer-",dir=output.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        for i,(row,base,base_ids,external) in enumerate(cache):
            _,ids,field,_=evaluate(grid[winner],row,base,base_ids,external)
            export_native(stage/"selected"/f"sample-{i:06d}",row,ids,field,grid[winner])
        for name,obj in (("selection.json",plan),("report.json",report)):
            (stage/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        stage.replace(output)
    print(json.dumps({"candidate":grid[winner],"qualification":"validation_only",
        "ranking":[{"recipe":r["recipe"],"balanced_f1":r["balanced"]["balanced_f1"],
                    "eligible":r["eligible"],"reasons":r["reasons"]} for r in sorted(ranking,key=lambda r:-r["balanced"]["balanced_f1"])]},indent=2))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--baseline",nargs=2,required=True)
    p.add_argument("--bundles",nargs="+",required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    a=p.parse_args();run(a.dataset,a.baseline,a.bundles,a.output,a.device)
