"""Local DINOv3 ViT-S/16 adaptation, with a learned dense feature pyramid.

No remote code, implicit downloads or claims of reconstructing HOT's ONNX
checkpoint. Import the licensed backbone from a local safetensors directory.
"""
from pathlib import Path
import json

import torch
from torch import nn
import torch.nn.functional as F

from imagery.raster import RasterError
from imagery.store import file_sha256


def backbone_identity(directory):
    root=Path(directory).resolve()
    paths=[root/"config.json",root/"model.safetensors"]
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise RasterError("Provide local DINOv3 config.json and model.safetensors.")
    config=json.loads(paths[0].read_text(encoding="utf-8"))
    if (config.get("model_type")!="dinov3_vit" or config.get("patch_size")!=16
            or config.get("hidden_size")!=384 or config.get("num_hidden_layers")!=12
            or config.get("num_attention_heads")!=6):
        raise RasterError("The supported pretrained backbone is DINOv3 ViT-S/16.")
    return {p.name:file_sha256(p) for p in paths}


class LowRankLinear(nn.Module):
    """Zero-initialized residual adapter; exact merge into the frozen base."""
    def __init__(self, base, rank=8, alpha=16.):
        super().__init__()
        if not 1<=rank<=min(base.in_features,base.out_features):
            raise ValueError("Invalid low-rank adapter size.")
        self.base=base
        self.base.requires_grad_(False)
        self.a=nn.Parameter(torch.empty(rank,base.in_features,device=base.weight.device,dtype=base.weight.dtype))
        self.b=nn.Parameter(torch.zeros(base.out_features,rank,device=base.weight.device,dtype=base.weight.dtype))
        nn.init.kaiming_uniform_(self.a,a=5**.5)
        self.scale=alpha/rank

    def forward(self,x):
        return self.base(x)+self.scale*F.linear(F.linear(x,self.a),self.b)

    def merged(self):
        base=self.base
        with torch.no_grad():
            base.weight.add_(self.scale*(self.b@self.a))
        return base


def inject_lora(encoder, rank=8):
    """Adapt attention projections only; refuse an unrecognized module layout."""
    selected=[]
    for name,module in list(encoder.named_modules()):
        if isinstance(module,nn.Linear) and "attention" in name.split("."):
            selected.append((name,module))
    if not selected:
        # Some supported implementations use 'attn' instead of 'attention'.
        selected=[(n,m) for n,m in encoder.named_modules()
                  if isinstance(m,nn.Linear) and "attn" in n.split(".")]
    if not selected:
        raise RasterError("DINOv3 attention projections were not found.")
    for name,module in selected:
        parent,_,leaf=name.rpartition(".")
        setattr(encoder.get_submodule(parent),leaf,LowRankLinear(module,rank))
    return [name for name,_ in selected]


def merge_lora(network):
    for name,module in list(network.named_modules()):
        if isinstance(module,LowRankLinear):
            parent,_,leaf=name.rpartition(".")
            setattr(network.get_submodule(parent),leaf,module.merged())


def conv(in_ch,out_ch,*,stride=1):
    return nn.Sequential(nn.Conv2d(in_ch,out_ch,3,stride=stride,padding=1,bias=False),
                         nn.GroupNorm(8,out_ch),nn.GELU(),
                         nn.Conv2d(out_ch,out_ch,3,padding=1,bias=False),
                         nn.GroupNorm(8,out_ch),nn.GELU())


def up(x,reference):
    return F.interpolate(x,size=reference.shape[-2:],mode="bilinear",align_corners=False)


class DinoBuilding(nn.Module):
    """Fuse four transformer depths and native RGB detail at 1/2,1/4,1/8 scales."""
    def __init__(self,encoder,width=64):
        super().__init__()
        self.encoder=encoder
        config=encoder.config
        self.patch=int(config.patch_size)
        self.prefix=1+int(config.num_register_tokens)
        layers=int(config.num_hidden_layers)
        if layers<4 or self.patch!=16 or width%8:
            raise ValueError("Unsupported DINO pyramid geometry.")
        self.depths=[layers//4,layers//2,3*layers//4,layers]
        self.norms=nn.ModuleList([nn.LayerNorm(config.hidden_size) for _ in self.depths])
        self.projections=nn.ModuleList([nn.Conv2d(config.hidden_size,width,1) for _ in self.depths])
        self.fuse=conv(4*width,width)
        self.detail2=conv(3,width//2,stride=2)
        self.detail4=conv(width//2,width,stride=2)
        self.detail8=conv(width,width,stride=2)
        self.decode8=conv(2*width,width)
        self.decode4=conv(2*width,width)
        self.decode2=conv(width+width//2,width//2)
        self.decode1=conv(width//2+3,width//2)
        self.segmentation_head=nn.Conv2d(width//2,3,1)

    def forward(self,x):
        output=self.encoder(pixel_values=x,output_hidden_states=True,return_dict=True)
        h,w=x.shape[-2]//self.patch,x.shape[-1]//self.patch
        grids=[]
        for depth,norm,project in zip(self.depths,self.norms,self.projections):
            tokens=norm(output.hidden_states[depth][:,self.prefix:])
            grids.append(project(tokens.transpose(1,2).reshape(x.shape[0],-1,h,w)))
        feature=self.fuse(torch.cat(grids,dim=1))
        d2=self.detail2(x);d4=self.detail4(d2);d8=self.detail8(d4)
        f8=self.decode8(torch.cat([up(feature,d8),d8],dim=1))
        f4=self.decode4(torch.cat([up(f8,d4),d4],dim=1))
        f2=self.decode2(torch.cat([up(f4,d2),d2],dim=1))
        return self.segmentation_head(self.decode1(torch.cat([up(f2,x),x],dim=1)))


def load_backbone(directory):
    from transformers import DINOv3ViTModel
    identity=backbone_identity(directory)
    encoder,info=DINOv3ViTModel.from_pretrained(str(Path(directory).resolve()),
        local_files_only=True,use_safetensors=True,attn_implementation="eager",
        output_loading_info=True)
    if any(info.get(key) for key in ("missing_keys","unexpected_keys","mismatched_keys","error_msgs")):
        raise RasterError("Backbone tensors do not exactly match the supported architecture.")
    if backbone_identity(directory)!=identity:
        raise RasterError("Backbone changed while loading.")
    return encoder.float().eval(),identity
