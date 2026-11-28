"""Run a pinned external building model on validation-only RGB chips.

Use each upstream project's own dependency environment. No server endpoint,
implicit checkpoint download, unsafe pickle fallback or label input.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision.building_dataset import load_dataset,canonical_sha
from vision.building_external import (upstream_identity,source_rgb,windows,coco_polygons,
                                      write_prediction)
from imagery.store import file_sha256


def safe_load(torch):
    original=torch.load
    def load(*args,**kwargs):
        kwargs["weights_only"]=True
        return original(*args,**kwargs)
    torch.load=load
    os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"]="1"


def unibuild_model(checkpoint,device):
    import torch
    from models.segmentation_model import SegmentationModel
    model=SegmentationModel({"backbone":{"name":"dinov3","variant":"base","pretrained":None},
                             "decoder":{"name":"hlrdpt"}},nclass=2)
    data=torch.load(str(checkpoint),map_location="cpu",weights_only=True)
    model.load_state_dict(data.get("state_dict",data),strict=True)
    return model.to(device).float().eval()


def unibuild_loader(checkpoint,device):
    import torch
    model=unibuild_model(checkpoint,device)
    def predict(rgb):
        size=512
        weight=np.maximum(np.outer(np.hanning(size),np.hanning(size)),1e-6).astype(np.float32)
        total=np.zeros(rgb.shape[:2],np.float32);support=np.zeros_like(total)
        mean=torch.tensor([.485,.456,.406],device=device)[None,:,None,None]
        std=torch.tensor([.229,.224,.225],device=device)[None,:,None,None]
        with torch.inference_mode():
            for y,x,h,w in windows(rgb.shape[:2],size,384):
                patch=np.zeros((size,size,3),np.uint8);patch[:h,:w]=rgb[y:y+h,x:x+w]
                tensor=torch.from_numpy(patch.transpose(2,0,1).copy())[None].to(device).float()/255.
                out=model((tensor-mean)/std)
                logits=out["logits"] if isinstance(out,dict) else out
                if logits.shape[-2:]!=(size,size):
                    logits=torch.nn.functional.interpolate(logits,size=(size,size),mode="bilinear",align_corners=False)
                if logits.shape[1]!=2:
                    raise ValueError("Unexpected UniBuild head layout.")
                p=torch.softmax(logits.float(),dim=1)[0,1,:h,:w].cpu().numpy()
                if not np.isfinite(p).all():
                    raise ValueError("Nonfinite UniBuild prediction.")
                total[y:y+h,x:x+w]+=p*weight[:h,:w]
                support[y:y+h,x:x+w]+=weight[:h,:w]
        if np.any(support<=0):
            raise ValueError("Incomplete UniBuild coverage.")
        return total/support
    return predict


def pix2poly_loader(checkpoint,device,variant="inria",encoder_cache=False):
    import torch
    from config import CFG
    from tokenizer import Tokenizer
    from models.model import Encoder,Decoder,EncoderDecoder
    from utils import test_generate,postprocess,permutations_to_polygons
    CFG.DEVICE=torch.device(device)
    from vision.building_pix2poly import configure_variant,cached_encoder
    from contextlib import nullcontext
    configure_variant(CFG,variant)
    tokenizer=Tokenizer(num_classes=1,num_bins=CFG.NUM_BINS,width=CFG.INPUT_WIDTH,
                        height=CFG.INPUT_HEIGHT,max_len=CFG.MAX_LEN)
    CFG.PAD_IDX=tokenizer.PAD_code
    encoder=Encoder(model_name=CFG.MODEL_NAME,pretrained=False,out_dim=256)
    decoder=Decoder(cfg=CFG,vocab_size=tokenizer.vocab_size,encoder_len=CFG.NUM_PATCHES,
                    dim=256,num_heads=8,num_layers=6)
    model=EncoderDecoder(cfg=CFG,encoder=encoder,decoder=decoder).to(device).eval()
    data=torch.load(str(checkpoint),map_location="cpu",weights_only=True)
    model.load_state_dict(data["state_dict"],strict=True)
    def predict(rgb):
        from shapely.geometry import Polygon
        size=224;tiles=windows(rgb.shape[:2],size,168)
        # Assign each polygon to the tile whose center is nearest its centroid.
        # Retain boundary truncation as a diagnostic limitation, not an oracle.
        centers=np.asarray([(y+h/2,x+w/2) for y,x,h,w in tiles])
        result=[]
        with torch.inference_mode():
            for index,(y,x,h,w) in enumerate(tiles):
                patch=np.zeros((size,size,3),np.uint8);patch[:h,:w]=rgb[y:y+h,x:x+w]
                tensor=torch.from_numpy(patch.transpose(2,0,1).copy())[None].to(device).float()/255.
                with (cached_encoder(model,tensor) if encoder_cache else nullcontext()):
                    pred,conf,perm=test_generate(model,tensor,tokenizer,max_len=CFG.generation_steps,top_k=0,top_p=1)
                coords,_=postprocess(pred,conf,tokenizer)
                coord=torch.as_tensor(coords[0],dtype=torch.float32) if coords[0] is not None else torch.empty((0,2))
                if len(coord)>CFG.N_VERTICES:
                    raise ValueError("Pix2Poly exceeded the configured vertex capacity.")
                graph=torch.cat([coord,torch.full((CFG.N_VERTICES-len(coord),2),float(CFG.PAD_IDX))]).to(perm.device)
                for poly in permutations_to_polygons(perm,[graph],out="torch")[0]:
                    poly=poly.detach().cpu().numpy()
                    poly=poly[poly[:,0]!=CFG.PAD_IDX]
                    if len(poly)<3:
                        continue
                    ring=poly[:,::-1].astype(np.float64)+[x,y]
                    geom=Polygon(ring)
                    if not geom.is_valid or geom.is_empty or geom.area<=0:
                        # Keep invalid predictions in the candidate diagnostics.
                        result.append({"rings":[ring.ravel().tolist()],"score":1.});continue
                    point=np.array([geom.centroid.y,geom.centroid.x])
                    if int(np.argmin(((centers-point)**2).sum(1)))==index:
                        result.append({"rings":[ring.ravel().tolist()],"score":1.})
        return result
    return predict


def sam_single_device_config(cfg):
    """Bound official prediction to one GPU, one image, no spawned workers."""
    loader=cfg.datamodule_cfg["predict_loader"]
    loader.update(batch_size=1,num_workers=0,persistent_workers=False,pin_memory=False)
    cfg.trainer_cfg.update(devices=[0],strategy="auto",accelerator="gpu",
                           use_distributed_sampler=False,benchmark=False)
    cfg.model_cfg.panoptic_head.roi_head.multi_process=False
    # No training callbacks or checkpoint creation during prediction.
    cfg.trainer_cfg["callbacks"]=[]
    cfg.trainer_cfg["enable_checkpointing"]=False
    return cfg


def sam_predict(checkpoint,root,rows,stage,score_threshold):
    from PIL import Image
    import infer_auto
    inputs=stage/"sam-input";inputs.mkdir()
    for row in rows:
        Image.fromarray(source_rgb(row["paths"]["image"])).save(inputs/f"{row['index']:06d}.png")
    work=stage/"sam-work"
    old=sys.argv[:]
    original=infer_auto.PLRunner
    class SingleDeviceRunner(original):
        @classmethod
        def from_cfg(cls,cfg):
            return super().from_cfg(sam_single_device_config(cfg))
    infer_auto.PLRunner=SingleDeviceRunner
    try:
        sys.argv=["infer_auto.py","--config",str(root/"configs/auto_whumix.py"),"--ckpt_path",str(checkpoint),
                  "--img_dir",str(inputs),"--img_suffix",".png","--work_dir",str(work),
                  "--score_thr",str(score_threshold),"--gpu","0"]
        infer_auto.main()
    finally:
        sys.argv=old
        infer_auto.PLRunner=original
    path=work/"whumix_auto"/"results.json"
    data=json.loads(path.read_text(encoding="utf-8"))
    known={f"{r['index']:06d}" for r in rows}
    if not isinstance(data,list) or any(str(r.get("image_id")) not in known for r in data):
        raise ValueError("Unexpected SAMPolyBuild image identifiers.")
    return {r["index"]:coco_polygons([a for a in data if str(a["image_id"])==f"{r['index']:06d}"],
                                    f"{r['index']:06d}") for r in rows}


def run(name,upstream,checkpoint,dataset_path,output,device,authorized,limit=None,*,pix_variant="inria",encoder_cache=False):
    import torch
    import importlib.metadata as metadata
    sys.dont_write_bytecode=True
    root=Path(upstream).resolve();checkpoint=Path(checkpoint).resolve()
    output=Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new external prediction directory.")
    identity=upstream_identity(name,root,checkpoint,authorized=authorized)
    dataset=load_dataset(dataset_path)
    rows=[{**r,"index":i} for i,r in enumerate(r for r in dataset["samples"] if r["split"]=="validation")]
    if limit is not None:
        rows=rows[:limit]
    if not rows:
        raise ValueError("No validation chips.")
    if device=="cuda" and not torch.cuda.is_available():
        raise ValueError("Requested CUDA is unavailable.")
    if name!="pix2poly" and (pix_variant!="inria" or encoder_cache):
        raise ValueError("Pix2Poly options require --model pix2poly.")
    if name=="sampolybuild" and device!="cuda":
        raise ValueError("The official SAMPolyBuild automatic runner requires CUDA.")
    safe_load(torch)
    torch.manual_seed(731);np.random.seed(731)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.backends.cudnn.benchmark=False
    versions={}
    for package in ("numpy","rasterio","torch","torchvision","transformers","timm","mmcv","mmengine",
                    "lightning","pytorch-lightning","opencv-python","opencv-python-headless","shapely","scipy"):
        try:
            versions[package]=metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
    settings={"device":device,"torch":str(torch.__version__),"seed":731,"dependencies":versions,
              "tile_size":512 if name=="unibuild" else 224 if name=="pix2poly" else None,
              "stride":384 if name=="unibuild" else 168 if name=="pix2poly" else None,
              "sam_score_threshold":.3 if name=="sampolybuild" else None,
              "sam_execution":"single_gpu_batch1_workers0" if name=="sampolybuild" else None,
              "pix_variant":pix_variant if name=="pix2poly" else None,
              "encoder_cache":encoder_cache if name=="pix2poly" else None,
              "pix_adapter_sha256":file_sha256(Path(__file__).resolve().parents[1]/"vision/building_pix2poly.py") if name=="pix2poly" else None,
              "checkpoint_loading":"weights_only","split":"validation","code_sha256":file_sha256(Path(__file__))}
    output.parent.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    oldcwd=Path.cwd();sys.path.insert(0,str(root));os.chdir(root)
    try:
        with TemporaryDirectory(prefix=".external-building-",dir=output.parent) as temp:
            stage=Path(temp);result=stage/"result";result.mkdir()
            if name=="sampolybuild":
                predictions=sam_predict(checkpoint,root,rows,stage,.3)
                predict=None
            else:
                predict=unibuild_loader(checkpoint,device) if name=="unibuild" else pix2poly_loader(checkpoint,device,pix_variant,encoder_cache)
            receipts=[]
            for row in rows:
                print(f"{name} validation {row['index']+1}: {row['id']}",flush=True)
                payload=predictions[row["index"]] if predict is None else predict(source_rgb(row["paths"]["image"]))
                folder=f"sample-{row['index']:06d}"
                receipt=write_prediction(result/folder,row["paths"]["image"],name,payload,identity,settings)
                receipts.append({"id":row["id"],"folder":folder,"prediction_sha256":receipt["sha256"]})
            if upstream_identity(name,root,checkpoint,authorized=authorized)!=identity:
                raise ValueError("External source or checkpoint changed during inference.")
            manifest={"model":identity,"settings":settings,"dataset_fingerprint":dataset["fingerprint"],
                      "samples":receipts,"test_evaluated":False,"seconds":time.monotonic()-start,
                      "peak_torch_allocated_mib":torch.cuda.max_memory_allocated()/1024**2 if device=="cuda" else None}
            manifest["sha256"]=canonical_sha(manifest)
            (result/"manifest.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n",encoding="utf-8")
            result.replace(output)
    finally:
        os.chdir(oldcwd);sys.path.remove(str(root))
    print(json.dumps(manifest,indent=2))
    return manifest


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",choices=("unibuild","sampolybuild","pix2poly"),required=True)
    p.add_argument("--upstream",type=Path,required=True)
    p.add_argument("--checkpoint",type=Path,required=True)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cuda")
    p.add_argument("--authorized",action="store_true")
    p.add_argument("--limit",type=int,choices=range(1,37))
    p.add_argument("--pix-variant",choices=("inria","spacenet","whu"),default="inria")
    p.add_argument("--encoder-cache",action="store_true",help="Opt-in cached image encoder; verify native prediction parity before ranking.")
    a=p.parse_args()
    run(a.model,a.upstream,a.checkpoint,a.dataset,a.output,a.device,a.authorized,a.limit,pix_variant=a.pix_variant,encoder_cache=a.encoder_cache)
