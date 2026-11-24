"""Global EOF decomposition and conditional circular-block trend bootstrap."""
import numpy as np
from analysis.science_raster import require

def eof(stack,p,kind):
    n,h,w=stack.shape;valid=np.isfinite(stack).all(axis=0);x=stack[:,valid]
    require(x.shape[1]>=3 and n*n*x.shape[1]<=40_000_000,'EOF requires complete time series and bounded covariance work.')
    # Center each location through time; use thin SVD instead of a spatial covariance matrix.
    x=x-x.mean(axis=0);u,s,vt=np.linalg.svd(x,full_matrices=False)
    total=float(s@s);require(total>0,'EOF requires temporal variation.')
    rank=int(np.count_nonzero(s>s[0]*1e-10));k=p['mode'];require(k<=rank,'Requested EOF mode exceeds numerical rank.')
    for j in range(rank):
        if vt[j,np.argmax(abs(vt[j]))]<0:u[:,j]*=-1;vt[j]*=-1
    fraction=s*s/total;reconstruction=(u[:,:k]*s[:k])@vt[:k]
    if kind=='eof_mode':v=vt[k-1]
    elif kind=='eof_reconstruction_rmse':v=np.sqrt(np.mean((x-reconstruction)**2,axis=0))
    else:
        # Local reconstruction skill may be negative: truncated global EOF
        # does not guarantee reduced residual error at each individual location.
        variance=np.sum(x*x,axis=0)
        v=1-np.divide(np.sum((x-reconstruction)**2,axis=0),variance,out=np.full(x.shape[1],np.nan),where=variance>0)
    out=np.full((h,w),np.nan);out[valid]=v
    return out,['mode','explained_fraction','cumulative_fraction'],[[j+1,float(fraction[j]),float(fraction[:j+1].sum())] for j in range(rank)],{
      'mode':k,'rank':rank,'complete_cells':int(valid.sum()),'explained_fraction':float(fraction[k-1]),'temporal_scores':(u[:,k-1]*s[k-1]).tolist(),
      'interpretation':'Unweighted complete-case EOF on temporally centered native cells; equal cell weight (projected metre grid required). Signs conventionally fixed, repeated eigenvalues have nonunique modes. Local skill is 1-SSE/SST, not a local explained variance fraction or causal model.'}

def block_trend(stack,t,p,kind):
    n,h,w=stack.shape;B=p['permutations'];L=p['block_length']
    require(n>=12 and 2<=L<=n//3 and n*h*w*(B+1)<=30_000_000,'Block bootstrap needs 12+ dates, block length 2 to n/3 and bounded work.')
    require(np.allclose(np.diff(t),np.diff(t)[0],rtol=1e-7,atol=1e-10),'Block bootstrap requires regular dates; missing values are not compressed.')
    valid=np.isfinite(stack).all(axis=0);require(valid.any(),'Block bootstrap requires complete observations.')
    x=stack[:,valid];tt=t-t.mean();den=tt@tt;slope=tt@x/den
    residual=x-x.mean(axis=0)-tt[:,None]*slope
    residual-=residual.mean(axis=0)
    # Shared resample indices preserve contemporaneous cross-pixel covariance.
    rng=np.random.default_rng(p['seed']);starts=rng.integers(0,n,(B,int(np.ceil(n/L))))
    idx=((starts[:,:,None]+np.arange(L))%n).reshape(B,-1)[:,:n]
    extreme=np.zeros(len(slope),int)
    for ids in idx:
        boot=tt@residual[ids]/den
        extreme+=np.abs(boot)>=np.abs(slope)
    q=(1+extreme)/(B+1)
    if kind=='block_trend_by':
        m=len(q);rank=np.arange(1,m+1);order=np.argsort(q);v=q.copy()
        v[order]=np.clip(np.minimum.accumulate((q[order]*m*np.sum(1/rank)/rank)[::-1])[::-1],0,1);q=v
    out=np.full((h,w),np.nan);out[valid]=q
    return out,{'replicates':B,'block_length':L,'seed':p['seed'],'complete_cells':int(valid.sum()),
     'interpretation':'Approximate null distribution of linear slope from circular moving-block resampling of detrended residuals, shared indices across cells. Requires regular complete series, stationary residuals and appropriate block length; not exact or universally serial-correlation robust. BY adjustment relies on valid marginal probabilities.'}
