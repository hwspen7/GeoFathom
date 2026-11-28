"""Instance-balanced supervision and bounded training-only hard sampling."""
import numpy as np
import torch
import torch.nn.functional as F
from scipy import ndimage as ndi

from .building_training import targets


def instance_targets(labels, instances):
    """Mask/boundary/distance plus true instance weights and shared-wall targets."""
    ids=np.asarray(instances)
    labels=np.asarray(labels)
    if (ids.shape!=labels.shape or ids.ndim!=2 or not np.issubdtype(ids.dtype,np.integer)
            or np.any(ids<0) or not np.array_equal(ids>0,labels==1)):
        raise ValueError("Independent instance supervision must match semantic labels.")
    _,inverse,counts=np.unique(ids,return_inverse=True,return_counts=True)
    # Inverse sqrt area with a hard cap protects small objects without making
    # single pixels dominate. Background always retains dense supervision.
    areas=counts[inverse].reshape(ids.shape)
    foreground=ids>0
    median=float(np.median(np.unique(ids[foreground],return_counts=True)[1])) if foreground.any() else 1.
    weights=np.where(foreground,np.clip(np.sqrt(median/areas),.5,4.),1.).astype(np.float32)
    shared=np.zeros(ids.shape,bool)
    padded=np.pad(ids,1)
    for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
        neighbor=padded[1+dy:1+dy+ids.shape[0],1+dx:1+dx+ids.shape[1]]
        shared|=foreground&(neighbor>0)&(neighbor!=ids)
    return np.concatenate([targets(labels,ids),weights[None],shared.astype(np.float32)[None]])


def instance_loss(raw, target, teacher=None, distillation_weight=.2):
    """Dense focal/Dice, object-balanced boundaries, signed distance consistency.

    The two-model teacher target is confidence- and label-agreement-gated;
    distillation never replaces supervised labels.
    """
    raw=raw.float();target=target.float()
    mask,boundary,distance,weight,shared=target.unbind(1)
    m,b,d=raw.unbind(1)
    p=torch.sigmoid(m);q=torch.sigmoid(b);signed=torch.tanh(d)
    # Average per chip, retain negative-only chips.
    pos=((1-mask).sum()/mask.sum().clamp_min(1)).clamp(1,6)
    bce=F.binary_cross_entropy_with_logits(m,mask,pos_weight=pos,reduction="none")
    pt=p*mask+(1-p)*(1-mask)
    def weighted(value,w):
        return ((value*w).flatten(1).sum(1)/w.flatten(1).sum(1).clamp_min(1)).mean()
    mask_loss=weighted(bce*(.5+(1-pt).square()),weight)
    dice=(1-(2*(p*mask).flatten(1).sum(1)+1)/((p+mask).flatten(1).sum(1)+1)).mean()
    bw=(1+3*shared+2*boundary)*weight
    boundary_loss=weighted(F.binary_cross_entropy_with_logits(b,boundary,reduction="none"),bw)
    boundary_dice=(1-(2*(q*boundary).flatten(1).sum(1)+1)/((q+boundary).flatten(1).sum(1)+1)).mean()
    distance_loss=weighted(F.smooth_l1_loss(signed,distance,reduction="none"),weight*(1+mask))
    consistency=weighted(F.binary_cross_entropy_with_logits(4*signed,mask,reduction="none"),
                         1+mask)
    result=mask_loss+dice+.65*boundary_loss+.25*boundary_dice+.4*distance_loss+.10*consistency
    if teacher is not None:
        # Teacher fields: probability and reliability on native pixels.
        soft,reliable=teacher.float().unbind(1)
        agrees=((soft>=.5)==(mask>=.5))
        gate=reliable*agrees*(2*(soft-.5).abs()).square()
        result=result+distillation_weight*weighted(
            F.binary_cross_entropy_with_logits(m,soft,reduction="none"),gate)
    return result


def teacher_targets(a,b):
    if not np.array_equal(a["valid"],b["valid"]):
        raise ValueError("Teacher source supports differ.")
    p,q=a["probability"],b["probability"]; valid=a["valid"]
    if (not np.isfinite(p[valid]).all() or not np.isfinite(q[valid]).all()
            or np.any((p[valid]<0)|(p[valid]>1)) or np.any((q[valid]<0)|(q[valid]>1))):
        raise ValueError("Invalid teacher probabilities.")
    return np.stack([np.where(valid,(p+q)*.5,.5),
                     np.where(valid,1-np.abs(p-q),0)]).astype(np.float32)


def group_balanced_order(groups, hardness, rng, count):
    """Sample groups uniformly, then chips by bounded difficulty within group."""
    if len(groups)!=len(hardness) or not groups or count<1:
        raise ValueError("Invalid training sampling inputs.")
    difficulty=np.asarray(hardness,np.float64)
    if not np.isfinite(difficulty).all() or np.any(difficulty<0):
        raise ValueError("Invalid training difficulty.")
    members={}
    for i,g in enumerate(groups):
        members.setdefault(g,[]).append(i)
    names=sorted(members)
    result=[]
    while len(result)<count:
        for g in rng.permutation(names):
            idx=np.asarray(members[g]);score=difficulty[idx]
            weights=np.clip(.5+score/max(float(score.mean()),1e-6),.5,2.5)
            result.append(int(rng.choice(idx,p=weights/weights.sum())))
            if len(result)==count:
                break
    return result
