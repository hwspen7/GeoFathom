"""Operator-local DINOv3 building adaptation; separate from legacy managed jobs."""
import json
import os
from pathlib import Path
import time
from tempfile import TemporaryDirectory
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
import rasterio

from imagery.raster import RasterError
from imagery.store import file_sha256
from .building_dataset import load_dataset,canonical_sha
from .building_training import augment_training_pair,export_model
from .building_study import _identity


class DinoOptions(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    mode:Literal["decoder","lora"]="decoder"
    rank:int=Field(default=8,ge=1,le=32)
    epochs:int=Field(default=20,ge=1,le=100)
    tile_size:int=Field(default=256,ge=64,le=512,multiple_of=32)
    batch_size:int=Field(default=2,ge=1,le=8)
    accumulation:int=Field(default=4,ge=1,le=32)
    crops_per_chip:int=Field(default=2,ge=1,le=8)
    learning_rate:float=Field(default=.0003,gt=0,le=.01,allow_inf_nan=False)
    seed:int=Field(default=731,ge=0,le=2147483647)
    device:Literal["cpu","cuda"]="cpu"
    precision:Literal["fp32","bf16"]="fp32"
    gpu_memory_mib:int=Field(default=12000,ge=1024,le=98304)
    cache_mb:int=Field(default=8192,ge=128,le=32768)
    patience:int=Field(default=5,ge=1,le=30)
    min_train_groups_per_region:int=Field(default=12,ge=1,le=36)
    min_train_chips:int=Field(default=100,ge=2,le=1000)
    distillation_weight:float=Field(default=.2,ge=0,le=.5,allow_inf_nan=False)
    teacher_device:Literal["cpu","cuda"]="cpu"


def normalization():
    return {"bands":[1,2,3],"input_scale":255.,"mean":[.485,.456,.406],"std":[.229,.224,.225]}


def audit_training_support(dataset,options):
    rows=[r for r in dataset["samples"] if r["split"]=="train"]
    groups={}
    for row in rows:
        groups.setdefault(row["region"],set()).add(row["group"])
    if (len(rows)<options.min_train_chips or len(groups)<2
            or any(len(g)<options.min_train_groups_per_region for g in groups.values())):
        raise RasterError("Insufficient training support: expand chips and independent source groups in at least two training regions.")
    if any("instances" not in r["paths"] for r in dataset["samples"] if r["split"] in ("train","validation")):
        raise RasterError("DINO adaptation requires independently supplied train and validation instance labels.")
    return {region:len(g) for region,g in sorted(groups.items())}


def crop_origins(shape,size):
    if min(shape)<size:
        raise RasterError("Training tile exceeds the native chip; select a smaller tile.")
    def starts(n):
        return sorted(set([*range(0,n-size+1,size),n-size]))
    return [(y,x) for y in starts(shape[0]) for x in starts(shape[1])]


def augment_crop(x,y,t,rng,config):
    # One paired spatial operation for RGB, supervision and teacher fields.
    joined=np.concatenate([y,t]) if t is not None else y
    x,joined=augment_training_pair(x,joined,rng,rgb_config=config)
    turns=int(rng.integers(0,4))
    x=np.ascontiguousarray(np.rot90(x,turns,axes=(-2,-1)))
    joined=np.ascontiguousarray(np.rot90(joined,turns,axes=(-2,-1)))
    return x,joined[:5],joined[5:] if t is not None else None


def train_dino(dataset_path,backbone,destination,options,*,teachers=(),progress=None):
    import torch
    from safetensors.torch import save_file,load_file
    from .building_dino import (DinoBuilding,load_backbone,backbone_identity,inject_lora,merge_lora)
    from .building_learning import instance_targets,instance_loss,teacher_targets,group_balanced_order
    from .building_prediction import predict_image
    options=DinoOptions.model_validate(options) if isinstance(options,dict) else options
    teachers=tuple(teachers)
    if teachers and (len(teachers)!=2 or len(set(teachers))!=2):
        raise RasterError("Distillation requires two distinct installed teachers.")
    if options.precision=="bf16" and options.device!="cuda":
        raise RasterError("BF16 training is supported only with CUDA.")
    if options.device=="cuda":
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")
        if not torch.cuda.is_available():
            raise RasterError("CUDA training requires a CUDA-enabled PyTorch installation.")
        if options.precision=="bf16" and not torch.cuda.is_bf16_supported():
            raise RasterError("The selected GPU does not support BF16.")
        total=torch.cuda.get_device_properties(0).total_memory
        if options.gpu_memory_mib*1024**2>total:
            raise RasterError("Requested training allocator limit exceeds GPU capacity.")
        torch.cuda.set_per_process_memory_fraction(options.gpu_memory_mib*1024**2/total,0)
        torch.cuda.reset_peak_memory_stats(0)
    destination=Path(destination)
    if destination.exists():
        raise RasterError("Training outputs already exist; choose a new directory.")
    dataset=load_dataset(dataset_path)
    groups=audit_training_support(dataset,options)
    source_id=backbone_identity(backbone)
    teacher_ids=[_identity(m) for m in teachers]
    torch.set_num_threads(min(4,os.cpu_count() or 1))
    torch.manual_seed(options.seed)
    rng=np.random.default_rng(options.seed)
    torch.use_deterministic_algorithms(True)
    device=torch.device(options.device)
    if options.device=="cuda":
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
        torch.backends.cudnn.benchmark=False
    config=normalization()
    destination.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    def tick(message):
        if progress:
            progress(message)
    with TemporaryDirectory(prefix=".dino-training-",dir=destination.parent) as temp:
        stage=Path(temp)
        cache=[];bytes_cached=0;foreground=0;background=0
        # Dataset integrity reads all source hashes; no test row is loaded for
        # augmentation, teacher predictions, optimizer or checkpoint selection.
        rows=[r for r in dataset["samples"] if r["split"] in ("train","validation")]
        for index,row in enumerate(rows):
            tick(f"cache {index+1}/{len(rows)} {row['split']} {row['id']}")
            with rasterio.open(row["paths"]["image"]) as src,rasterio.open(row["paths"]["labels"]) as lab,rasterio.open(row["paths"]["instances"]) as inst:
                rgb=src.read([1,2,3],masked=True)
                y=lab.read(1,masked=True)
                ids=inst.read(1)
                if np.ma.getmaskarray(rgb).any() or np.ma.getmaskarray(y).any():
                    raise RasterError("Training chips must be fully observed and labeled.")
                rgb=np.asarray(rgb.data,np.float32)
                if not np.isfinite(rgb).all() or np.any((rgb<0)|(rgb>255)):
                    raise RasterError("DINO training expects RGB samples encoded in [0,255].")
                rgb=(rgb/255-np.asarray(config["mean"],np.float32)[:,None,None])/np.asarray(config["std"],np.float32)[:,None,None]
                target=instance_targets(y.data,ids)
            origins=crop_origins(target.shape[-2:],options.tile_size)
            teach=None
            if row["split"]=="train":
                foreground+=int(target[0].sum());background+=target[0].size-int(target[0].sum())
                if teachers:
                    a,b=[predict_image(row["paths"]["image"],m,device=options.teacher_device,augmentation="flips") for m in teachers]
                    teach=teacher_targets(a,b)
            arrays=[rgb,target]+([teach] if teach is not None else [])
            bytes_cached+=sum(a.nbytes for a in arrays)
            if bytes_cached>options.cache_mb*1024**2:
                raise RasterError("DINO training cache exceeds the explicit disk allowance.")
            paths=[]
            for j,array in enumerate(arrays):
                path=stage/f"sample-{index}-{j}.npy";np.save(path,array);paths.append(path)
            cache.append({"row":row,"paths":paths,"origins":origins,
                          "difficulty":float(1+target[4].mean()*8+(target[3]>1.5).mean()*4)})
        if not foreground or not background:
            raise RasterError("Training requires both foreground and background.")
        encoder,loaded_id=load_backbone(backbone)
        if loaded_id!=source_id:
            raise RasterError("Backbone changed before training.")
        encoder.requires_grad_(False)
        network=DinoBuilding(encoder)
        adapters=inject_lora(encoder,options.rank) if options.mode=="lora" else []
        network.to(device)
        network.encoder.eval()
        trainable=[p for p in network.parameters() if p.requires_grad]
        parameter_count=sum(p.numel() for p in trainable)
        backbone_config=encoder.config.to_dict()
        optimizer=torch.optim.AdamW(trainable,lr=options.learning_rate,weight_decay=.0001)
        scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=options.epochs,eta_min=options.learning_rate*.05)
        train=[r for r in cache if r["row"]["split"]=="train"]
        validation=[r for r in cache if r["row"]["split"]=="validation"]
        hardness=np.array([r["difficulty"] for r in train],np.float64)
        size=options.tile_size
        def read(entry,origin,training):
            y,x=origin
            arrays=[np.load(p,mmap_mode="r")[:,y:y+size,x:x+size] for p in entry["paths"]]
            a,b=arrays[:2];t=arrays[2] if len(arrays)>2 else None
            return augment_crop(a,b,t,rng,config) if training else (a,b,None)
        def batch(items,training):
            values=[read(e,o,training) for e,o in items]
            x=torch.from_numpy(np.stack([v[0] for v in values])).to(device)
            y=torch.from_numpy(np.stack([v[1] for v in values])).to(device)
            t=torch.from_numpy(np.stack([v[2] for v in values])).to(device) if training and teachers else None
            with torch.autocast(device_type=options.device,dtype=torch.bfloat16,enabled=options.precision=="bf16"):
                raw=network(x)
            loss=instance_loss(raw,y,t,options.distillation_weight)
            if not torch.isfinite(loss):
                raise RasterError("Nonfinite DINO training objective.")
            return loss
        def validate():
            network.eval()
            total=0.;count=0
            entries=[(e,o) for e in validation for o in e["origins"]]
            with torch.no_grad():
                for i in range(0,len(entries),options.batch_size):
                    block=entries[i:i+options.batch_size]
                    total+=float(batch(block,False))*len(block);count+=len(block)
            if not count:
                raise RasterError("Validation has no complete crops.")
            return total/count
        best=stage/"best.safetensors"
        def save_best():
            save_file({k:v.detach().cpu().contiguous() for k,v in network.state_dict().items()},str(best))
        best_loss=validate();best_epoch=0
        history=[{"epoch":0,"validation_loss":best_loss,"training_loss":None}]
        save_best()
        for epoch in range(1,options.epochs+1):
            network.train();network.encoder.eval()
            order=group_balanced_order([e["row"]["group"] for e in train],hardness,rng,len(train)*options.crops_per_chip)
            entries=[]
            for i in order:
                e=train[i];arr=np.load(e["paths"][1],mmap_mode="r")
                # Draw native crop from uniform and boundary-rich alternatives.
                candidates=[(int(rng.integers(0,arr.shape[1]-size+1)),int(rng.integers(0,arr.shape[2]-size+1))) for _ in range(3)]
                def difficulty(o):
                    y,x=o
                    return float(arr[4,y:y+size,x:x+size].mean()+.2*arr[1,y:y+size,x:x+size].mean())
                origin=max(candidates,key=difficulty) if rng.random()<.5 else candidates[0]
                entries.append((i,e,origin))
            epoch_loss=0.;count=0
            # Accumulate gradients normalized by actual crop count, including
            # the incomplete final accumulation group.
            span=options.batch_size*options.accumulation
            for offset in range(0,len(entries),span):
                window=entries[offset:offset+span]
                optimizer.zero_grad(set_to_none=True)
                for i in range(0,len(window),options.batch_size):
                    micro=window[i:i+options.batch_size]
                    loss=batch([(e,o) for _,e,o in micro],True)
                    (loss*len(micro)/len(window)).backward()
                    value=float(loss.detach());epoch_loss+=value*len(micro);count+=len(micro)
                    for idx,_,_ in micro:
                        hardness[idx]=.8*hardness[idx]+.2*value
                torch.nn.utils.clip_grad_norm_(trainable,1.,error_if_nonfinite=True)
                optimizer.step()
            value=validate()
            history.append({"epoch":epoch,"training_loss":epoch_loss/count,"validation_loss":value,
                            "learning_rate":optimizer.param_groups[0]["lr"]})
            tick(f"epoch {epoch}: train={epoch_loss/count:.6f} validation={value:.6f}")
            if value<best_loss:
                best_loss,best_epoch=value,epoch;save_best()
            scheduler.step()
            if epoch-best_epoch>=options.patience:
                break
        network.load_state_dict(load_file(str(best)),strict=True)
        network.eval().float()
        # Measure the adapter merge before export; all exported weights are FP32.
        sample=torch.zeros((1,3,size,size),device=device)
        with torch.no_grad():
            before=network(sample).float().cpu()
            merge_lora(network)
            after=network(sample).float().cpu()
        if not torch.isfinite(before).all() or not torch.isfinite(after).all() or not torch.allclose(before,after,atol=2e-4,rtol=2e-4):
            raise RasterError("LoRA merge failed dense logit parity.")
        merge_error=float((before-after).abs().max())
        manifest={**config,"task":"building_extraction","classes":["background","building"],
            "tile_size":size,"halo":size//8,"output_type":"binary_logits","output_channels":3,
            "output_channel":0,"boundary_channel":1,"distance_channel":2,"max_batch":1,
            "description":"Locally trained DINOv3 feature pyramid building candidate",
            "backbone_architecture":"dinov3_vits16_pyramid","backbone_config":backbone_config,
            "training":{"dataset_fingerprint":dataset["fingerprint"],"backbone":source_id,
                        "teachers":teacher_ids,"parameters":options.model_dump(),"best_epoch":best_epoch,
                        "selection":"minimum supervised validation crop loss; no test fitting"}}
        output=stage/"output"
        parity=export_model(network,output,manifest)
        if (backbone_identity(backbone)!=source_id or [_identity(m) for m in teachers]!=teacher_ids
                or load_dataset(dataset_path,verify_pixels=False)["fingerprint"]!=dataset["fingerprint"]):
            raise RasterError("Training input identities changed.")
        report={"dataset_fingerprint":dataset["fingerprint"],"counts":dataset["counts"],"train_groups":groups,
            "parameters":options.model_dump(),"backbone":source_id,"teachers":teacher_ids,
            "history":history,"best_epoch":best_epoch,"initial_validation_loss":history[0]["validation_loss"],
            "selected_validation_loss":best_loss,"validation_improved":best_epoch>0,
            "trainable_parameters":parameter_count,"lora_modules":adapters,"lora_merge_max_error":merge_error,
            "cache_bytes":bytes_cached,"test_used_for_training":False,"onnx_parity":parity,
            "model_sha256":file_sha256(output/"model.onnx"),"checkpoint_sha256":file_sha256(output/"model.safetensors"),
            "torch_version":str(torch.__version__),"seconds":round(time.monotonic()-started,3),
            "peak_torch_allocated_mib":torch.cuda.max_memory_allocated(0)/1024**2 if options.device=="cuda" else None,
            "peak_torch_reserved_mib":torch.cuda.max_memory_reserved(0)/1024**2 if options.device=="cuda" else None,
            "qualification":"validation_loss_only","note":"Actual mask and object metrics, CUDA inference qualification and independent holdout still required."}
        (output/"training.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        output.replace(destination)
    return report
