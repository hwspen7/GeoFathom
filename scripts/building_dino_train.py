"""Train a local licensed DINOv3 backbone; never download weights implicitly."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--backbone",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--teachers",nargs=2)
    parser.add_argument("--teacher-device",choices=("cpu","cuda"),default="cpu")
    parser.add_argument("--mode",choices=("decoder","lora"),default="decoder")
    parser.add_argument("--rank",type=int,default=8)
    parser.add_argument("--epochs",type=int,default=20)
    parser.add_argument("--tile-size",type=int,default=256)
    parser.add_argument("--batch-size",type=int,default=2)
    parser.add_argument("--accumulation",type=int,default=4)
    parser.add_argument("--crops-per-chip",type=int,default=2)
    parser.add_argument("--learning-rate",type=float,default=.0003)
    parser.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    parser.add_argument("--precision",choices=("fp32","bf16"),default="fp32")
    parser.add_argument("--gpu-memory-mib",type=int,default=12000)
    parser.add_argument("--cache-mb",type=int,default=8192)
    parser.add_argument("--patience",type=int,default=5)
    parser.add_argument("--distillation-weight",type=float,default=.2)
    parser.add_argument("--warm-start",type=Path,help="Verified prior decoder or LoRA run on the same frozen dataset.")
    parser.add_argument("--install-as")
    args=parser.parse_args()
    from vision.building_dino_training import train_dino
    values=vars(args).copy()
    for key in ("dataset","backbone","output","teachers","warm_start","install_as"):
        values.pop(key)
    report=train_dino(args.dataset,args.backbone,args.output,values,teachers=args.teachers or (),warm_start=args.warm_start,progress=lambda text:print(text,flush=True))
    if args.install_as:
        from vision.building_research_store import install_training_model
        report["installed"]=install_training_model(args.output,args.install_as)
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=="__main__":
    main()
