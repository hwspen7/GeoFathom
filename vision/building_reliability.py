"""Multi-scale local reliability proxy on aligned source pixels."""
import numpy as np
from scipy import ndimage as ndi

from imagery.raster import RasterError

HALO=9


def fuse_reliability(primary, secondary, primary_delta, secondary_delta, valid, weight=.5):
    """Use multi-scale view consistency and damp adaptation at ambiguous edges.

    Odds multipliers are capped at two around the validated prior; reliability
    is not a calibrated probability of correctness. Supports haloed blocks.
    """
    valid=np.asarray(valid,bool)
    a,b,da,db=(np.asarray(f,np.float32) for f in (primary,secondary,primary_delta,secondary_delta))
    if valid.ndim!=2 or not 0<=weight<=1:
        raise RasterError("Invalid reliability fusion prior or grid.")
    for field in (a,b,da,db):
        if (field.shape!=valid.shape or not np.isfinite(field[valid]).all()
                or np.any((field[valid]<0)|(field[valid]>1))):
            raise RasterError("Reliability fusion requires finite aligned probabilities.")
    if weight in (0,1):
        return np.where(valid,a if weight==0 else b,-1).astype(np.float32)
    support=valid.astype(np.float32)
    delta=np.where(valid,da-db,0)
    reliability=np.zeros(valid.shape,np.float32)
    for size,factor in ((5,.45),(9,.35),(17,.20)):
        count=ndi.uniform_filter(support,size=size,mode="constant")
        reliability+=factor*ndi.uniform_filter(delta,size=size,mode="constant")/np.maximum(count,1e-6)
    average=np.where(valid,(a+b)*.5,0)
    # Near a steep common boundary, keep the fixed prior dominant.
    hi=ndi.maximum_filter(np.where(valid,average,-1),size=3,mode="nearest")
    lo=ndi.minimum_filter(np.where(valid,average,2),size=3,mode="nearest")
    edge=np.clip(hi-lo,0,1)
    change=np.clip(3*reliability*(1-.5*edge),-np.log(2.),np.log(2.))
    odds=weight/(1-weight)*np.exp(change)
    w=odds/(1+odds)
    return np.where(valid,(1-w)*a+w*b,-1).astype(np.float32)
