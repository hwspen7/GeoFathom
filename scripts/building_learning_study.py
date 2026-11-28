"""Compare trained candidates against the earlier frozen double-model baseline."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from imagery.store import file_sha256
from vision.building_dataset import load_dataset,canonical_sha
from vision.building_prediction import predict_image
from vision.building_ensemble_study import ensemble_fields
from vision.building_study import score_fields,aggregate,balanced_validation_score,_identity
from vision.building_qualification import POLICY,paired_gate
from scripts.building_advanced_study import BASELINE,code_identity,write_bundle


def grid(baseline,candidates):
    first,second=baseline
    rows=[{"models":list(baseline),**BASELINE}]
    for model in candidates:
        for members,weights in (([model],[0.]),([model,second],[.25,.5])):
            for weight in weights:
                for aug in ("none","flips"):
                    for threshold in (.30,.35,.40,.50):
                        for mode in ("adaptive","graph"):
                            rows.append({"models":members,"augmentation":aug,"fusion_mode":"fixed",
                                         "secondary_weight":weight,"probability_threshold":threshold,
                                         "instance_mode":mode,"seed_distance":6})
    return rows


def identity():
    return canonical_sha({"advanced":code_identity(),"learning_script":file_sha256(Path(__file__).resolve())})


def evaluate(rows,recipes,device):
    records=[[] for _ in recipes]
    for index,row in enumerate(rows):
        print(f"{row['split']} {index+1}/{len(rows)} {row['id']}",flush=True)
        cached={};fields={}
        for j,r in enumerate(recipes):
            aug=r["augmentation"]
            key=(tuple(r["models"]),aug,r["secondary_weight"])
            if key not in fields:
                views=[]
                for model in r["models"]:
                    if (model,aug) not in cached:
                        cached[model,aug]=predict_image(row["paths"]["image"],model,device=device,augmentation=aug)
                    views.append(cached[model,aug])
                fields[key]=ensemble_fields(*views,r["secondary_weight"],"fixed") if len(views)==2 else views[0]
            m,_=score_fields(fields[key],row,r["probability_threshold"],r["instance_mode"],r["seed_distance"])
            records[j].append({"sample_id":row["id"],"region":row["region"],"group":row["group"],"metrics":m})
    return records


def pick(records,excluded=None):
    filtered=[[r for r in a if r["group"]!=excluded] for a in records]
    stats=[aggregate(a) for a in filtered]
    base=stats[0]
    eligible=[i for i,m in enumerate(stats)
              if m["classes"][1]["f1"]>=base["classes"][1]["f1"]-.01-1e-12
              and m["objects_75"]["f1"]>=base["objects_75"]["f1"]-.01-1e-12]
    return max(eligible,key=lambda i:(balanced_validation_score(filtered[i])["balanced_f1"],
                                     stats[i]["objects_75"]["f1"],stats[i]["objects_50"]["f1"],i==0,-i))


def run(dataset_path,baseline,candidates,output,device,selection=None):
    if Path(output).exists():
        raise ValueError("Output exists; preserve study evidence.")
    baseline=list(baseline);candidates=list(candidates)
    if (len(baseline)!=2 or not 1<=len(candidates)<=4 or
            len(set(baseline+candidates))!=len(baseline+candidates)):
        raise ValueError("Provide two distinct baseline models and one to four distinct new candidates.")
    dataset=load_dataset(dataset_path)
    models=[_identity(m) for m in baseline+candidates]
    code=identity()
    recipes=grid(baseline,candidates)
    if selection is None:
        rows=[r for r in dataset["samples"] if r["split"]=="validation"]
        results=evaluate(rows,recipes,device)
        i=pick(results)
        plan={"dataset_fingerprint":dataset["fingerprint"],"models":models,"code_sha256":code,
              "device":device,"baseline":recipes[0],"candidate":recipes[i],"grid":recipes,
              "policy":dict(POLICY),"test_used_for_selection":False}
        plan["sha256"]=canonical_sha(plan)
        folds=[];crossfit=[]
        groups=sorted({r["group"] for r in rows})
        if len(groups)>1:
            for group in groups:
                choice=pick(results,excluded=group)
                folds.append({"group":group,"recipe":recipes[choice]})
                crossfit.extend(r for r in results[choice] if r["group"]==group)
        report={"selection":plan,"validation":[{"recipe":r,"aggregate":aggregate(v),
                 "balanced":balanced_validation_score(v)} for r,v in zip(recipes,results)],
                "baseline":aggregate(results[0]),"candidate":aggregate(results[i]),
                "baseline_records":results[0],"candidate_records":results[i],
                "group_crossfit":{"folds":folds,"aggregate":aggregate(crossfit) if crossfit else None},
                "test_evaluated":False,"qualification":{"status":"validation_only","passed":False}}
    else:
        plan=json.loads(Path(selection).read_text(encoding="utf-8"))
        if (plan.get("sha256")!=canonical_sha({k:v for k,v in plan.items() if k!="sha256"})
                or plan.get("dataset_fingerprint")!=dataset["fingerprint"] or plan.get("models")!=models
                or plan.get("code_sha256")!=code or plan.get("device")!=device
                or plan.get("baseline")!=recipes[0] or plan.get("grid")!=recipes
                or plan.get("candidate") not in recipes or plan.get("policy")!=dict(POLICY)
                or plan.get("test_used_for_selection") is not False):
            raise ValueError("Frozen learning selection mismatch.")
        if plan["candidate"]==plan["baseline"]:
            raise ValueError("No new candidate qualified for a holdout comparison; leave the test split closed.")
        rows=[r for r in dataset["samples"] if r["split"]=="test"]
        a,b=evaluate(rows,[plan["baseline"],plan["candidate"]],device)
        report={"selection":plan,"test_evaluated":True,"baseline":aggregate(a),"candidate":aggregate(b),
                "baseline_records":a,"candidate_records":b,"qualification":paired_gate(a,b)}
    if ([_identity(m) for m in baseline+candidates]!=models or identity()!=code or
            load_dataset(dataset_path,verify_pixels=False)["fingerprint"]!=dataset["fingerprint"]):
        raise ValueError("Learning study inputs changed.")
    report["note"]="Candidate selection and paired comparison only; no automatic model promotion. Pretraining overlap is not established."
    write_bundle(output,{"selection.json":plan,"report.json":report})
    print(json.dumps({"candidate":plan["candidate"],"qualification":report["qualification"]["status"],
                      "baseline":{k:report["baseline"][k]["f1"] for k in ("objects_50","objects_75")},
                      "candidate_scores":{k:report["candidate"][k]["f1"] for k in ("objects_50","objects_75")}},indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--baseline",nargs=2,required=True)
    parser.add_argument("--candidates",nargs="+",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    parser.add_argument("--selection",type=Path)
    args=parser.parse_args()
    run(args.dataset,args.baseline,args.candidates,args.output,args.device,args.selection)
