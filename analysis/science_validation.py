"""Spatial block bootstrap for paired satellite/reference accuracy and model comparison."""
import numpy as np
from .science_raster import require

def blocked_accuracy(grids,p,kind):
    """Resample occupied spatial blocks, not individual pixels.

    For comparisons, both estimates use the identical reference support and
    identical bootstrap resamples. Blocks are treated as exchangeable
    independent clusters; no spatial independence is guaranteed by a grid.
    """
    g=grids[0]
    require(g.is_meter,"Spatial accuracy inference requires a projected metre grid.")
    require(bool(g.unit) and all(x.unit==g.unit for x in grids),"Declare matching continuous physical units.")
    require(g.unit!="class","Continuous accuracy methods do not accept class rasters.")
    require(all(x.crs==g.crs and x.transform==g.transform and x.values.shape==g.values.shape for x in grids),"Explicitly align all validation rasters.")
    stack=np.stack([x.values for x in grids]);common=np.isfinite(stack).all(axis=0)
    require(common.any(),"No common finite validation observations.")
    rr,cc=np.nonzero(common)
    require(len(rr)<=2_000_000,"Validation exceeds two million cells.")
    east,north=g.axes
    size=p["block_m"]
    block=np.column_stack((np.floor(east[cc]/size),np.floor(north[rr]/size))).astype(np.int64)
    keys,ids,count=np.unique(block,axis=0,return_inverse=True,return_counts=True)
    n=len(count)
    require(8<=n<=5000,"Use 8–5,000 occupied blocks; adjust block size or study region.")
    require(n*p["replicates"]<=10_000_000,"Block bootstrap work exceeds budget.")
    reference=stack[-1][common]
    errors=[stack[i][common]-reference for i in range(len(grids)-1)]
    def sums(x):
        return np.stack([np.bincount(ids,weights=v,minlength=n) for v in (x,abs(x),x*x)],axis=1)
    aggregates=np.stack([sums(x) for x in errors],axis=0)
    require(np.isfinite(aggregates).all(),"Validation moments overflow.")
    def score(s,c):
        return np.stack((s[...,0]/c,s[...,1]/c,np.sqrt(np.maximum(s[...,2]/c,0))),axis=-1)
    observed=score(aggregates.sum(axis=1),count.sum())
    rng=np.random.default_rng(p["seed"]);draws=np.empty((p["replicates"],len(errors),3))
    for i in range(p["replicates"]):
        sampled=np.bincount(rng.integers(0,n,size=n),minlength=n)
        s=np.einsum("mbj,b->mj",aggregates,sampled)
        draws[i]=score(s,sampled@count)
    names=["bias","mae","rmse"]
    def intervals(a):
        return {name:[float(v) for v in np.quantile(a[...,j],[.025,.975])] for j,name in enumerate(names)}
    meta={"paired_cells":int(common.sum()),"occupied_blocks":n,"block_m":size,
        "bootstrap_replicates":p["replicates"],"seed":p["seed"],"confidence":.95,
        "first_metrics":dict(zip(names,map(float,observed[0]))),"first_interval95":intervals(draws[:,0]),
        "assumptions":"exchangeable independent spatial blocks; observed common-support pixel weighting; conditional percentile intervals, not external ground-truth certification"}
    block_scores=score(aggregates,count[None,:])
    headers=["block_x_m","block_y_m","count","first_bias","first_mae","first_rmse"]
    rows=np.column_stack(((keys+.5)*size,count,block_scores[0]))
    out=np.full(g.values.shape,np.nan)
    if kind=="blocked_reference_accuracy":
        out[common]=errors[0]
    else:
        delta=observed[1]-observed[0]
        meta.update(second_metrics=dict(zip(names,map(float,observed[1]))),
            second_interval95=intervals(draws[:,1]),second_minus_first=dict(zip(names,map(float,delta))),
            paired_difference_interval95=intervals(draws[:,1]-draws[:,0]))
        headers+=["second_bias","second_mae","second_rmse","mae_difference"]
        rows=np.column_stack((rows,block_scores[1],block_scores[1,:,1]-block_scores[0,:,1]))
        out[common]=abs(errors[1])-abs(errors[0])
    return out,headers,rows.tolist(),meta
