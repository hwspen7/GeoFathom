"""Bounded scientific models on explicitly aligned raster time series."""
import numpy as np
from scipy.special import ndtr
from analysis.science_raster import require

def trend(stack,t,kind):
    n,h,w=stack.shape
    require(n*n*h*w<=30_000_000,'Pairwise trend work budget exceeded.')
    count=np.isfinite(stack).sum(axis=0);out=np.full((h,w),np.nan)
    for row,col in zip(*np.where(count>=6)):
        good=np.isfinite(stack[:,row,col]);x=stack[good,row,col];time=t[good];m=len(x)
        i,j=np.triu_indices(m,1);d=x[j]-x[i]
        if kind=='sen':out[row,col]=np.median(d/(time[j]-time[i]));continue
        s=np.sign(d).sum();ties=np.unique(x,return_counts=True)[1]
        var=(m*(m-1)*(2*m+5)-np.sum(ties*(ties-1)*(2*ties+5)))/18
        z=(s-np.sign(s))/np.sqrt(var) if var>0 and s else 0.
        out[row,col]=2*ndtr(-abs(z))
    if kind=='mk_by_q':
        valid=np.isfinite(out);p=out[valid];m=len(p)
        if m:
            order=np.argsort(p);rank=np.arange(1,m+1);factor=np.sum(1/rank)
            adjusted=np.minimum.accumulate((p[order]*m*factor/rank)[::-1])[::-1]
            q=np.empty(m);q[order]=np.clip(adjusted,0,1);out[valid]=q
    return out,{'minimum_observations':6,'inference':'Sen slope uses actual time differences. MK uses tie-corrected asymptotic normal approximation and assumes temporally independent observations; BY controls FDR under arbitrary cross-pixel dependence only if marginal p-values are valid. No serial-correlation correction.'}

def temporal(stack,t,kind,p):
    n,h,w=stack.shape;valid=np.isfinite(stack);count=valid.sum(axis=0);out=np.full((h,w),np.nan)
    if kind=='coverage':return count.astype(float)/n,{'acquisitions':n}
    if kind=='exceedance':
        np.divide(np.sum(valid&(stack>p['threshold']),axis=0),count,out=out,where=count>=p['minimum_observations'])
        return out,{'threshold':p['threshold'],'interpretation':'Observed exceedance fraction, not duration or occurrence probability under nonrandom missingness.'}
    require(np.allclose(np.diff(t),np.diff(t)[0],rtol=1e-7,atol=1e-10),'Lag analysis requires a regular time axis; do not compress missing dates.')
    lag=p['lag'];require(lag<n-2,'Lag exceeds time axis.')
    a,b=stack[:-lag],stack[lag:];ok=np.isfinite(a)&np.isfinite(b);m=ok.sum(axis=0)
    den=np.maximum(m,1);aa=np.where(ok,a,0);bb=np.where(ok,b,0)
    am=aa.sum(axis=0)/den;bm=bb.sum(axis=0)/den
    x=np.where(ok,a-am,0);y=np.where(ok,b-bm,0)
    norm=np.sqrt(np.sum(x*x,axis=0))*np.sqrt(np.sum(y*y,axis=0))
    np.divide(np.sum(x*y,axis=0),norm,out=out,where=(m>=p['minimum_observations'])&(norm>0))
    return np.clip(out,-1,1),{'lag_steps':lag,'lag_time':float(t[lag]-t[0]),'interpretation':'Pairwise complete lagged Pearson correlation; descriptive, not an AR coefficient or significance test.'}

def forecast(stack,t,kind,p):
    """Fixed-design trend prediction evaluated on strictly future holdouts."""
    n,h,w=stack.shape
    require(n*h*w<=1_500_000,'Forecast work budget exceeded.')
    horizon=p['horizon'];cut=p['minimum_observations'];require(cut+2<=n,'Need training observations and at least two future dates.')
    out=np.full((h,w),np.nan);rows=[];squared=np.zeros(n);baseline=np.zeros(n);counts=np.zeros(n,int)
    origin=t[0];scale=t[-1]-origin;u=(t-origin)/scale
    future=u[-1]+horizon/scale
    for r,c in zip(*np.where(np.isfinite(stack).sum(axis=0)>=cut)):
        y=stack[:,r,c];ok=np.isfinite(y)
        def fit(mask,x):
            a=np.column_stack((np.ones(mask.sum()),u[mask]));z=y[mask]
            b,_,rank,_=np.linalg.lstsq(a,z,rcond=None)
            if rank!=2:return None
            v=np.array([1.,x]);prediction=float(v@b)
            residual=z-a@b
            sd=float(np.sqrt(max(0,(residual@residual)/(len(z)-2)*(1+v@np.linalg.solve(a.T@a,v))))) if len(z)>2 else np.nan
            return prediction,sd
        if kind in ('forecast_mean','forecast_sd'):
            result=fit(ok,future)
            if result is not None:out[r,c]=result[kind=='forecast_sd']
        else:
            errors=[];naive=[]
            for j in range(cut,n):
                train=ok&(np.arange(n)<j)
                if not ok[j] or train.sum()<cut:continue
                result=fit(train,u[j])
                if result is None:continue
                e=(result[0]-y[j])**2;b=(y[np.flatnonzero(train)[-1]]-y[j])**2
                errors.append(e);naive.append(b);squared[j]+=e;baseline[j]+=b;counts[j]+=1
            if len(errors)>=2:
                rmse=np.sqrt(np.mean(errors))
                out[r,c]=rmse if kind=='hindcast_rmse' else (1-np.sum(errors)/np.sum(naive) if np.sum(naive)>0 else np.nan)
    for j in np.flatnonzero(counts):rows.append([float(t[j]),int(counts[j]),float(np.sqrt(squared[j]/counts[j])),float(np.sqrt(baseline[j]/counts[j]))])
    return out,['time','pairs','trend_rmse','persistence_rmse'],rows,{'forecast_time':float(t[-1]+horizon),'validation':'Expanding-window, strictly earlier observations only; skill = 1-SSEtrend/SSEpersistence. Prediction SD assumes independent homoscedastic Gaussian residuals and a correctly specified linear trend; not calibrated under temporal dependence.'}

def spatial_lag(stack,kind,p):
    n,h,w=stack.shape;require(n*h*w<=2_000_000,'Space-time lag work budget exceeded.')
    # Standardize each date separately; remove changing scene-wide level,
    # with no spatial interpolation and rook adjacency only.
    z=np.full_like(stack,np.nan)
    for i,a in enumerate(stack):
        ok=np.isfinite(a)
        if ok.sum()>=3:
            sd=a[ok].std()
            if sd>0:z[i,ok]=(a[ok]-a[ok].mean())/sd
    total=np.zeros((h,w));count=np.zeros((h,w),int)
    rows=[]
    for i in range(1,n):
        previous=z[i-1];current=z[i];s=np.zeros((h,w));k=np.zeros((h,w),int)
        for src,dst in ((np.s_[:-1,:],np.s_[1:,:]),(np.s_[1:,:],np.s_[:-1,:]),(np.s_[:,:-1],np.s_[:,1:]),(np.s_[:,1:],np.s_[:,:-1])):
            a=previous[src];ok=np.isfinite(a);s[dst]+=np.where(ok,a,0);k[dst]+=ok
        good=np.isfinite(current)&(k>0);v=np.zeros((h,w));v[good]=current[good]*s[good]/k[good]
        total+=v;count+=good
        rows.append([i+1,int(good.sum()),float(v[good].mean()) if good.any() else None])
    out=np.full((h,w),np.nan);np.divide(total,count,out=out,where=count>=p['minimum_observations'])
    return out,['acquisition','cells','lag_product'],rows,{'interpretation':'Mean product of date-standardized cell value and previous acquisition rook-neighbor mean. Descriptive space-time association, not a Moran significance test. Irregular lags retain acquisition-order meaning.'}

def variogram(stack,t,grid,p):
    n,h,w=stack.shape;lag=p['lag'];r=p['radius'];require(grid.is_meter,'Space-time variogram requires projected metre coordinates.')
    require(lag<n and n*h*w*(r+1)*(lag+1)<=40_000_000,'Variogram work budget exceeded.')
    # Directional horizontal and vertical offsets separately, regular time
    # axis; pair count and squared differences pooled without independence claim.
    require(np.allclose(np.diff(t),np.diff(t)[0],rtol=1e-7,atol=1e-10),'Variogram requires a regular time axis.')
    rows=[]
    for k in range(lag+1):
        for d in range(r+1):
            if k==d==0:continue
            for axis in ('east','north') if d else ('temporal',):
                if (axis=='east' and d>=w) or (axis=='north' and d>=h):continue
                a=stack[:n-k];b=stack[k:]
                if axis=='east':a,b=a[:,:,:w-d],b[:,:,d:]
                elif axis=='north':a,b=a[:,:h-d,:],b[:,d:,:]
                ok=np.isfinite(a)&np.isfinite(b);delta=a[ok]-b[ok]
                if len(delta):
                    distance=d*(grid.transform.a if axis=='east' else abs(grid.transform.e))
                    rows.append([axis,float(distance),float(k*(t[1]-t[0])),int(len(delta)),float(.5*np.mean(delta**2))])
    require(rows,'No valid space-time pairs.')
    return ['direction','space_m','time_lag','pairs','semivariance'],rows,{'interpretation':'Empirical directional space-time semivariance of native paired observations; no fitted covariance, stationarity assumption required for modeling. Pair counts are not independent sample sizes.'}
