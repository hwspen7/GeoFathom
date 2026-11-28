"""Freeze production-compatible building parameters, then independently qualify."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from imagery.store import file_sha256
from vision.building_dataset import canonical_sha, load_dataset
from vision.building_ensemble_study import ensemble_fields
from vision.building_prediction import predict_image
from vision.building_profile import create_profile
from vision.building_qualification import POLICY, paired_gate
from vision.building_reliability import fuse_reliability
from vision.building_study import aggregate, balanced_validation_score, score_fields, _identity


def recipe_grid():
    # Candidate grid is fixed before validation. Baseline is the earlier flip
    # winner, with no new postprocessing or threshold changes.
    return [{"augmentation":aug,"fusion_mode":fusion,"secondary_weight":weight,
             "probability_threshold":threshold,"instance_mode":mode,"seed_distance":seed}
            for aug,fusion in (("flips","fixed"),("hybrid","fixed"),("hybrid","spatial"))
            for weight in (.25,.5,.75) for threshold in (.30,.35,.40)
            for mode in ("adaptive","graph") for seed in (6,10)]


BASELINE={"augmentation":"flips","fusion_mode":"fixed","secondary_weight":.5,
          "probability_threshold":.35,"instance_mode":"adaptive","seed_distance":6}


def code_identity():
    root=Path(__file__).resolve().parents[1]
    paths=[Path(__file__).resolve(), *sorted((root/"vision").glob("building*.py")),
           root/"vision/semantic.py",root/"vision/tiled.py",root/"vision/tiles.py",root/"core/cuda_environment.py"]
    return canonical_sha({str(p.relative_to(root)):file_sha256(p) for p in paths})


def select(records, recipes, baseline_index, excluded_group=None):
    def filtered(rows):
        return [r for r in rows if r["group"]!=excluded_group]
    stats=[aggregate(filtered(r)) for r in records]
    base=stats[baseline_index]
    eligible=[i for i,a in enumerate(stats) if a["classes"][1]["f1"]>=base["classes"][1]["f1"]-.01-1e-12
              and a["objects_75"]["f1"]>=base["objects_75"]["f1"]-.01-1e-12]
    return max(eligible,key=lambda i:(balanced_validation_score(filtered(records[i]))["balanced_f1"],
              stats[i]["objects_75"]["f1"],stats[i]["objects_50"]["f1"],i==baseline_index,-i))


def evaluate_rows(rows, recipes, models, device):
    records=[[] for _ in recipes]
    for index,row in enumerate(rows):
        print(f"{row['split']} {index+1}/{len(rows)}: {row['id']}",flush=True)
        views={}; fields={}
        for aug in sorted({r["augmentation"] for r in recipes}):
            views[aug]=[predict_image(row["paths"]["image"],m,device=device,augmentation=aug) for m in models]
        for j,r in enumerate(recipes):
            key=(r["augmentation"],r["fusion_mode"],r["secondary_weight"])
            if key not in fields:
                a,b=views[key[0]]
                if key[1]=="spatial":
                    if not np.array_equal(a["valid"],b["valid"]):
                        raise ValueError("Model supports disagree.")
                    fields[key]={**a,"probability":fuse_reliability(a["probability"],b["probability"],
                        a["view_disagreement"],b["view_disagreement"],a["valid"],key[2])}
                else:
                    fields[key]=ensemble_fields(a,b,key[2],key[1])
            metrics,_=score_fields(fields[key],row,r["probability_threshold"],r["instance_mode"],r["seed_distance"])
            records[j].append({"sample_id":row["id"],"region":row["region"],"group":row["group"],"metrics":metrics})
    return records


def write_bundle(output, objects):
    output=Path(output)
    if output.exists():
        raise ValueError("Output exists; preserve the frozen experiment.")
    output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix=".advanced-",dir=output.parent) as temp:
        stage=Path(temp)/"result";stage.mkdir()
        for name,value in objects.items():
            (stage/name).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        stage.replace(output)


def run(dataset_path, models, output, device, *, selection_path=None):
    if Path(output).exists():
        raise ValueError("Output exists; preserve the frozen experiment.")
    dataset=load_dataset(dataset_path)
    identities=[_identity(m) for m in models]
    code=code_identity()
    if selection_path is None:
        recipes=recipe_grid()
        baseline_index=recipes.index(BASELINE)
        rows=[r for r in dataset["samples"] if r["split"]=="validation"]
        records=evaluate_rows(rows,recipes,models,device)
        winner=select(records,recipes,baseline_index)
        groups=sorted({r["group"] for r in rows})
        crossfit=[]; chosen=[]
        if len(groups)>1:
            for group in groups:
                i=select(records,recipes,baseline_index,excluded_group=group)
                crossfit.extend(r for r in records[i] if r["group"]==group)
                chosen.append({"held_out_group":group,"recipe":recipes[i]})
        plan={"dataset_fingerprint":dataset["fingerprint"],"models":identities,"device":device,
              "code_sha256":code,"baseline":BASELINE,"candidate":recipes[winner],"grid":recipes,
              "qualification_policy":dict(POLICY),"test_used_for_selection":False}
        plan["sha256"]=canonical_sha(plan)
        report={"selection":plan,"validation":[{"recipe":r,"aggregate":aggregate(v),
                  "balanced":balanced_validation_score(v)} for r,v in zip(recipes,records)],
                "group_crossfit":{"folds":chosen,"aggregate":aggregate(crossfit) if crossfit else None},
                "baseline_records":records[baseline_index],"candidate_records":records[winner],
                "test_evaluated":False,"note":"Group crossfit uses the validation region only; it is not cross-city evidence."}
        qualification=None
    else:
        plan=json.loads(Path(selection_path).read_text(encoding="utf-8"))
        if (plan.get("sha256")!=canonical_sha({k:v for k,v in plan.items() if k!="sha256"})
                or plan.get("dataset_fingerprint")!=dataset["fingerprint"] or plan.get("models")!=identities
                or plan.get("code_sha256")!=code or plan.get("device")!=device
                or plan.get("baseline")!=BASELINE or plan.get("grid")!=recipe_grid()
                or plan.get("candidate") not in recipe_grid() or plan.get("qualification_policy")!=dict(POLICY)
                or plan.get("test_used_for_selection") is not False):
            raise ValueError("Frozen selection, code, dataset, model or device mismatch.")
        rows=[r for r in dataset["samples"] if r["split"]=="test"]
        baseline,candidate=evaluate_rows(rows,[plan["baseline"],plan["candidate"]],models,device)
        qualification=paired_gate(baseline,candidate)
        report={"selection":plan,"test_evaluated":True,"baseline":aggregate(baseline),
                "candidate":aggregate(candidate),"baseline_records":baseline,"candidate_records":candidate,
                "qualification":qualification,"note":"Never auto-promoted. Pretraining overlap requires separate audit."}
    if ([_identity(m) for m in models]!=identities or code_identity()!=code
            or load_dataset(dataset_path,verify_pixels=False)["fingerprint"]!=dataset["fingerprint"]):
        raise ValueError("Study inputs changed during execution.")
    deployment={"model_id":models[0],"secondary_model_id":models[1],**plan["candidate"]}
    profile=create_profile(plan,deployment,qualification)
    write_bundle(output,{"selection.json":plan,"report.json":report,"profile.json":profile})
    print(json.dumps({"candidate":plan["candidate"],"qualification":profile["reported_qualification"]},indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--models",nargs=2,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    parser.add_argument("--selection",type=Path,help="Explicitly evaluate test using a frozen validation receipt.")
    args=parser.parse_args()
    run(args.dataset,args.models,args.output,args.device,selection_path=args.selection)
