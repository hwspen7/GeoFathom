"""Balanced two-way fixed effects with spatial block cluster uncertainty."""
import numpy as np
from scipy.stats import t as student
from analysis.science_raster import require

def panel(y,x,p,kind):
    n,h,w=y.shape;require(y.shape==x.shape,'Covariate cube must align exactly.')
    valid=np.isfinite(y).all(axis=0)&np.isfinite(x).all(axis=0)
    r,c=np.where(valid);m=len(r);require(m>=12,'Panel needs at least 12 complete locations.')
    require(n*m<=1_000_000,'Panel work budget exceeded.')
    a=y[:,valid];b=x[:,valid]
    def demean(z):return z-z.mean(axis=0)-z.mean(axis=1,keepdims=True)+z.mean()
    a0=demean(a);b0=demean(b)
    scale=float(np.max(abs(b0)));require(scale>0 and scale>1e-10*max(float(np.max(abs(b))),1e-100),'Covariate is absorbed by spatial/time fixed effects.')
    z=b0/scale;den=float(np.sum(z*z));coef=float(np.sum(z*a0)/den);beta=coef/scale
    e=a0-coef*z
    block=p['block_cells'];_,groups=np.unique(np.column_stack((r//block,c//block)),axis=0,return_inverse=True);G=int(groups.max()+1)
    require(G>=4,'Cluster inference requires at least four spatial blocks; more are needed for credible asymptotics.')
    scores=np.bincount(groups,weights=np.sum(z*e,axis=0))
    df=n*m-(n+m-1)-1;require(df>0,'No residual degrees of freedom.')
    correction=G/(G-1)*(n*m-1)/df
    se=float(np.sqrt(correction*np.sum(scores**2))/den/scale)
    prob=float(2*student.sf(abs(beta/se),G-1)) if se>0 else None
    spatial=a.mean(axis=0)-beta*b.mean(axis=0)
    temporal=a.mean(axis=1)-beta*b.mean(axis=1);grand=float(spatial.mean())
    if kind=='panel_spatial_effect':v=spatial-grand
    elif kind=='panel_residual_rmse':v=np.sqrt(np.mean(e*e,axis=0))
    else:v=e[-1]
    out=np.full((h,w),np.nan);out[valid]=v
    rows=[[i+1,float(temporal[i]-grand),float(np.sqrt(np.mean(e[i]**2)))] for i in range(n)]
    return out,['acquisition','time_effect','residual_rmse'],rows,{'coefficient':beta,'cluster_robust_se':se,'p_value':prob,'clusters':G,'complete_locations':m,'residual_df':df,
        'within_r2':float(1-np.sum(e*e)/np.sum(a0*a0)) if np.sum(a0*a0)>0 else None,
        'interpretation':'Balanced two-way fixed effects with one time-varying covariate; CR1 spatial block clustered sandwich, t reference G-1 df. Arbitrary dependence within blocks, independence across blocks assumed. Small cluster count unreliable; no causal or prediction claim.'}
