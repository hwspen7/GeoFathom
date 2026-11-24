"""Gaussian-kernel geographically and temporally weighted multivariate regression."""
import numpy as np
from analysis.science_raster import require

def local_fit(coords,X,y,target,p):
    ds=np.sum(((coords[:,:2]-target[:2])/p['spatial_range'])**2,axis=1)
    dt=((coords[:,2]-target[2])/p['temporal_range'])**2
    logw=-.5*(ds+dt)
    # Do not silently normalize away lack of support in remote extrapolation.
    if logw.max() < -12.5:return None
    weights=np.exp(logw-logw.max());eff=weights.sum()**2/(weights@weights)
    if eff<max(p['effective_samples'],X.shape[1]+2):return None
    A=X*np.sqrt(weights[:,None]);b=y*np.sqrt(weights)
    if np.linalg.matrix_rank(A)<X.shape[1] or np.linalg.cond(A)>1e7:return None
    coef=np.linalg.lstsq(A,b,rcond=None)[0]
    return coef,float(eff)

def gtwr(y,cubes,t,grid,p,kind):
    require(grid.is_meter,'GTWR requires projected metre coordinates.')
    n,h,w=y.shape;cov=np.asarray(cubes)
    require(cov.ndim==4 and cov.shape[1:]==y.shape and 1<=len(cov)<=3,'GTWR requires one to three aligned covariate cubes.')
    hold=kind=='gtwr_holdout_rmse';cut=n-p.get('holdout_dates',0);border=w-w//3
    require(not hold or (cut>=4 and w>=3 and border>p['buffer_cells']),'Insufficient joint holdout support.')
    valid=np.isfinite(y)&np.isfinite(cov).all(axis=0);train=valid.copy()
    if hold:train[cut:]=False;train[:,:,border-p['buffer_cells']:]=False
    ids=np.argwhere(train);require(len(ids)>=16,'Insufficient GTWR training observations.')
    rng=np.random.default_rng(p['seed'])
    if len(ids)>p['local_sample_limit']:ids=ids[np.sort(rng.choice(len(ids),p['local_sample_limit'],replace=False))]
    def xyz(a):
        i,r,c=a.T;return np.column_stack(((c+.5)*grid.transform.a,(r+.5)*abs(grid.transform.e),t[i]-t[0]))
    loc=xyz(ids);raw=cov[:,ids[:,0],ids[:,1],ids[:,2]].T
    center=raw.mean(axis=0);sd=raw.std(axis=0);require(np.all(sd>0),'Training covariates must vary.')
    X=np.column_stack((np.ones(len(ids)),(raw-center)/sd));z=y[tuple(ids.T)]
    require(np.linalg.matrix_rank(X)==X.shape[1],'Collinear training covariates.')
    coefidx=p.get('coefficient_index',1)-1;require(hold or coefidx<len(cov),'Coefficient index exceeds covariate count.')
    if hold:
        mask=valid.copy();mask[:cut]=False;mask[:,:,:border]=False
    else:
        mask=np.zeros_like(valid);mask[-1]=np.isfinite(cov[:,-1]).all(axis=0)
    test=np.argwhere(mask);require(len(test)*len(ids)*(X.shape[1]**2)<=30_000_000,'GTWR evaluation work budget exceeded.')
    output=np.full((h,w),np.nan);total=np.zeros((h,w));counts=np.zeros((h,w),int);rows=[];effective=[];errors=[];baseline=[]
    for a,b in zip(test,xyz(test)):
        i,r,c=a;fit=local_fit(loc,X,z,b,p)
        if fit is None:continue
        beta,eff=fit;effective.append(eff)
        if hold:
            pred=float(beta@np.r_[1.,(cov[:,i,r,c]-center)/sd]);err=pred-y[i,r,c]
            total[r,c]+=err*err;counts[r,c]+=1;errors.append(float(err));baseline.append(float(z.mean()-y[i,r,c]))
        else:output[r,c]=beta[coefidx+1]/sd[coefidx] if kind=='gtwr_coefficient' else eff
    if hold:
        np.divide(total,counts,out=output,where=counts>0);output=np.sqrt(output)
    require(effective,'No local regression passed rank, conditioning and effective sample checks.')
    for q in np.linspace(0,1,21):rows.append([float(q),float(np.quantile(effective,q))])
    meta={'training_indices':ids.tolist(),'training_samples':len(ids),'covariate_count':len(cov),'evaluated_targets':len(test),'supported_targets':len(effective),'coefficient_index':coefidx+1 if not hold else None,
      'interpretation':'Fixed Gaussian spatial and temporal bandwidths; training-only covariate scaling; weighted least squares with rank/condition/effective-support checks. Latest-date coefficients are descriptive local associations. Joint holdout uses known test covariates but no test response for training; no causal or coefficient significance claim.'}
    if hold:meta.update(rmse=float(np.sqrt(np.mean(np.square(errors)))),training_mean_rmse=float(np.sqrt(np.mean(np.square(baseline)))),training_end_exclusive=cut,spatial_holdout_start_column=border)
    return output,['quantile','effective_samples'],rows,meta
