"""Additional spatial research kernels.

All estimators declare their sampling population. Raster distances are exact
Euclidean cell-center distances; no-data is not an impassable barrier.
"""
import numpy as np
from .science_raster import require

def edt_line(f,spacing):
    """Lower envelope of parabolas, O(n), including all-infinite scan lines."""
    candidates=np.flatnonzero(np.isfinite(f));n=len(f)
    if not len(candidates):return np.full(n,np.inf)
    v=np.empty(len(candidates),np.int64);cuts=np.empty(len(candidates)+1)
    k=0;v[0]=candidates[0];cuts[0]=-np.inf;cuts[1]=np.inf;s2=spacing*spacing
    for q in candidates[1:]:
        p=v[k];s=((f[q]-f[p])/s2+q*q-p*p)/(2*(q-p))
        while k>0 and s<=cuts[k]:
            k-=1;p=v[k];s=((f[q]-f[p])/s2+q*q-p*p)/(2*(q-p))
        k+=1;v[k]=q;cuts[k]=s;cuts[k+1]=np.inf
    out=np.empty(n);j=0
    for q in range(n):
        while j<k and cuts[j+1]<q:j+=1
        out[q]=f[v[j]]+s2*(q-v[j])**2
    return out

def euclidean_distance(z,dx,dy):
    valid=np.isfinite(z);require(np.isin(z[valid],[0,1]).all() and np.any(z==1),'Distance requires a binary target grid with at least one target cell.')
    cost=np.where(z==1,0.,np.inf)
    for i in range(cost.shape[0]):cost[i]=edt_line(cost[i],dx)
    for j in range(cost.shape[1]):cost[:,j]=edt_line(cost[:,j],dy)
    out=np.sqrt(cost);out[~valid]=np.nan
    return out

def focal_quantile(z,r,q):
    # Bounded row chunks prevent materializing a complete 4-D window tensor.
    from numpy.lib.stride_tricks import sliding_window_view
    import warnings
    size=2*r+1;require(z.size*size*size<=24_000_000,'Quantile neighborhood exceeds work budget.')
    windows=sliding_window_view(np.pad(z,r,constant_values=np.nan),(size,size))
    out=np.full_like(z,np.nan)
    for start in range(0,z.shape[0],max(1,250000//(z.shape[1]*size*size))):
        end=min(z.shape[0],start+max(1,250000//(z.shape[1]*size*size)))
        block=windows[start:end]
        # All-NaN windows have a defined missing output.
        valid=np.isfinite(z[start:end])
        if valid.any():out[start:end][valid]=np.nanquantile(block[valid],q,axis=(1,2))
    return out

def lag_scan(z,dx,dy,max_lag):
    """Directional empirical semivariances, covariance and correlation on paired cells."""
    rows=[];h,w=z.shape;require(z.size*max_lag<=20_000_000,'Lag scan exceeds cell budget.')
    for direction,step,limit in [('E-W',dx,w),('N-S',dy,h)]:
        for k in range(1,min(max_lag,limit-1)+1):
            a,b=(z[:,:-k],z[:,k:]) if direction=='E-W' else (z[:-k,:],z[k:,:])
            valid=np.isfinite(a)&np.isfinite(b);a=a[valid];b=b[valid]
            if len(a)<2:continue
            ac=a-a.mean();bc=b-b.mean();den=np.sqrt((ac@ac)*(bc@bc))
            rows.append([direction,k,k*step,len(a),float(np.mean((a-b)**2)/2),float(ac@bc/len(a)),float(ac@bc/den) if den else None])
    require(rows,'No valid directional lag pairs.')
    return ['direction','lag_cells','distance_m','pairs','semivariance','covariance','correlation'],rows

def bivariate_moran(a,b,permutations,seed):
    """Directed cross-variable global Moran statistic and random-label null for B."""
    from .science_raster import adjacency
    common=np.isfinite(a)&np.isfinite(b);x,i,j=adjacency(np.where(common,a,np.nan));y=b[common];n=len(x)
    require(n>=3 and len(i)>0 and x.std()>0 and y.std()>0,'Cross-Moran requires varying paired cells with rook neighbors.')
    x=(x-x.mean())/x.std();y=(y-y.mean())/y.std()
    source=np.r_[i,j];target=np.r_[j,i];degree=np.bincount(source,minlength=n)
    require((len(source)+n)*(permutations+1)<=30_000_000,'Cross-Moran permutation budget exceeded.')
    eligible=degree>0
    def stat(v):
        lag=np.divide(np.bincount(source,weights=v[target],minlength=n),degree,out=np.zeros(n),where=eligible)
        return float(np.mean((x*lag)[eligible]))
    observed=stat(y);rng=np.random.default_rng(seed);null=np.array([stat(rng.permutation(y)) for _ in range(permutations)])
    p=(1+np.count_nonzero(abs(null)>=abs(observed)-1e-14))/(permutations+1)
    return {'observed':observed,'expected':0.,'p_two_sided':float(p),'valid_cells':n,'tested_cells':int(eligible.sum()),'permutations':permutations},null

def robust_overlay(stack,common,weights,directions,draws,concentration,threshold,seed):
    """Sensitivity to explicitly specified Dirichlet weight uncertainty."""
    k=len(stack);w=np.asarray(weights,float);require(w.shape==(k,) and np.all(np.isfinite(w)) and np.all(w>0) and np.max(w)<=1e100,'Provide positive finite weights.')
    require(len(directions)==k and all(d in ('benefit','cost') for d in directions),'Choose benefit or cost for every criterion.')
    w=w/w.sum();require(np.all(w*concentration>=1e-5),'Dirichlet shapes too small for numerical stability.')
    x=stack[:,common].T;require(len(x)*k*draws<=80_000_000,'Weight-uncertainty work budget exceeded.')
    span=np.ptp(x,axis=0);v=np.divide(x-x.min(axis=0),span,out=np.full_like(x,.5),where=span>0)
    v[:,np.asarray(directions)=='cost']=1-v[:,np.asarray(directions)=='cost']
    rng=np.random.default_rng(seed);mean=np.zeros(len(x));m2=np.zeros(len(x));hit=np.zeros(len(x),np.int32)
    for i,draw in enumerate(rng.dirichlet(w*concentration,size=draws),1):
        score=v@draw;delta=score-mean;mean+=delta/i;m2+=delta*(score-mean);hit+=score>=threshold
    def grid(q):
        out=np.full(common.shape,np.nan);out[common]=q;return out
    return {'mean':grid(mean),'sd':grid(np.sqrt(m2/max(1,draws-1))),'probability':grid(hit/draws)}, {'draws':draws,'concentration':concentration,'threshold':threshold,'normalized_weights':w.tolist(),'model':'Dirichlet weight uncertainty conditional on fixed criterion rasters; not calibrated event probability.'}

def blocked_raster_regression(grids,params):
    """Out-of-fold prediction on the complete-case raster grid, no spatial leakage across buffers."""
    from terrain.studio_data import aligned_grids
    from terrain.studio_calibrated_models import block_regression
    stack,common=aligned_grids(grids,require_same_unit=False);g=grids[0]
    require(g.is_meter,'Spatial validation requires a projected metre grid.')
    require(12<=common.sum()<=20000,'Block regression requires 12–20,000 complete cells; explicitly aggregate or crop first.')
    yy,xx=np.nonzero(common);east,north=g.axes;coords=np.column_stack((east[xx],north[yy]))
    actual=stack[0,common];x=stack[1:,common].T
    pred,fold,report=block_regression(coords,x,actual,params['block_size_m'],params['folds'],params['ridge_penalty'],params['buffer_m'])
    residual=actual-pred;rmse=float(np.sqrt(np.mean(residual**2)));ss=float(np.sum((actual-actual.mean())**2))
    output=np.full(common.shape,np.nan);output[common]=pred
    report.update(rmse=rmse,mae=float(np.mean(abs(residual))),r_squared=1-float(residual@residual)/ss if ss>0 else None,validation_count=len(actual))
    # Keep generic model diagnostics distinct from hydrological flow metrics.
    report.pop('overall',None)
    report['folds']=[{k:v for k,v in row.items() if k in {'fold','training_count','validation_count','validation_blocks','buffer_excluded','rmse','mae','bias','r_squared'}} for row in report['folds']]
    rows=[[float(a),float(b),float(v),float(p),float(r),int(f)] for (a,b),v,p,r,f in zip(coords,actual,pred,residual,fold)]
    return output,['easting','northing','observed','prediction','residual','fold'],rows,report
