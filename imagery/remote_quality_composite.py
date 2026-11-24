"""Explicit quality-weighted reflectance composites; quality is not precision."""
import numpy as np
from analysis.science_raster import require

QUALITY_IDS={"quality_weighted_mean","quality_weighted_sd","quality_effective_count"}

def quality_composite(v,p,kind):
    x=np.stack([v[f"observation{i}"] for i in range(1,4)])
    w=np.stack([v[f"quality{i}"] for i in range(1,4)])
    valid=np.isfinite(x)&np.isfinite(w)&(w>0)
    w=np.where(valid,w,0.)
    x=np.where(valid,x,0.)
    total=w.sum(axis=0)
    count=valid.sum(axis=0)
    good=(count>=p["minimum_observations"])&(total>0)
    mean=np.divide((x*w).sum(axis=0),total,out=np.full(total.shape,np.nan),where=good)
    if kind=="quality_weighted_mean":out=mean
    elif kind=="quality_weighted_sd":
        var=np.divide((w*(x-np.where(good,mean,0.))**2).sum(axis=0),total,out=np.full(total.shape,np.nan),where=good)
        out=np.sqrt(var)
    else:
        out=np.divide(total**2,(w*w).sum(axis=0),out=np.full(total.shape,np.nan),where=good)
    return out,{"valid_output_cells":int(good.sum()),"minimum_observations":p["minimum_observations"],
        "zero_weight_or_missing_pairs":int((~valid).sum()),
        "assumption":"three comparable reflectance acquisitions with supplied quality weights; SD is weighted observed spread, effective count is Kish support, not independent uncertainty"}
