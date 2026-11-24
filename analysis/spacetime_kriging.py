"""Bounded ordinary space-time kriging with training-only REML and joint holdout."""
import numpy as np
from scipy.linalg import cho_factor,cho_solve
from scipy.spatial.distance import cdist
from scipy.optimize import minimize
from analysis.science_raster import require

def fit(x,y,p):
    # Normalize response using training data only; nugget is relative to sill.
    center=float(y.mean());scale=float(y.std());require(scale>0,'Training observations must vary.')
    z=(y-center)/scale
    ds=cdist(x[:,:2],x[:,:2]);dt=cdist(x[:,2:],x[:,2:])
    ones=np.ones(len(z))
    def model(theta):
        rs,rt,ratio=np.exp(theta)
        K=np.exp(-ds/rs-dt/rt)+ratio*np.eye(len(z))
        factor=cho_factor(K,lower=True,check_finite=True)
        u=cho_solve(factor,ones);den=float(ones@u);mean=float(u@z/den)
        residual=z-mean;alpha=cho_solve(factor,residual)
        sill=float(residual@alpha/(len(z)-1))
        require(np.isfinite(sill) and sill>0,'Degenerate covariance fit.')
        objective=(len(z)-1)*np.log(sill)+2*np.log(np.diag(factor[0])).sum()+np.log(den)
        return objective,(rs,rt,ratio,factor,u,den,mean,alpha,sill)
    init=np.log([p['spatial_range'],p['temporal_range'],p['nugget_ratio']])
    if p['fit_covariance']:
        require(len(x)<=256,'REML fitting limited to 256 training samples.')
        bounds=[(v-np.log(10),v+np.log(10)) for v in init]
        result=minimize(lambda a:model(a)[0],init,method='L-BFGS-B',bounds=bounds,options={'maxiter':100,'maxfun':600,'ftol':1e-9})
        require(result.success,'REML covariance optimization failed; revise starting scales or use fixed ranges.')
        theta=result.x
        boundary=bool(any(min(abs(v-lo),abs(v-hi))<1e-4 for v,(lo,hi) in zip(theta,bounds)))
    else:theta=init;boundary=False
    obj,(rs,rt,ratio,factor,u,den,mean,alpha,sill)=model(theta)
    def predict(target):
        mu=[];sd=[]
        for i in range(0,len(target),256):
            v=target[i:i+256]
            cross=np.exp(-cdist(x[:,:2],v[:,:2])/rs-cdist(x[:,2:],v[:,2:])/rt)
            solved=cho_solve(factor,cross)
            variance=1+ratio-np.sum(cross*solved,axis=0)+(1-u@cross)**2/den
            require(np.min(variance)>=-1e-8,'Invalid kriging variance.')
            mu.extend(center+scale*(mean+cross.T@alpha));sd.extend(scale*np.sqrt(sill*np.maximum(variance,0)))
        return np.asarray(mu),np.asarray(sd)
    return predict,{'spatial_range':float(rs),'temporal_range':float(rt),'nugget_ratio':float(ratio),'sill':float(sill*scale**2),'reml_objective':float(obj),'fit_at_bound':boundary,
        'covariance_fitted':bool(p['fit_covariance']),'training_mean':center,'training_samples':len(x)}

def kriging(stack,t,grid,p,kind):
    n,h,w=stack.shape
    require(grid.is_meter,'Kriging requires projected metre coordinates.')
    hold=kind.startswith('st_holdout_');cut=n-p['holdout_dates']
    require(not hold or (cut>=4 and w>=3),'Holdout needs four training dates and at least three columns.')
    # Contiguous right-hand spatial block held out at all dates; final dates
    # held out across the entire scene. Optional buffer separates training.
    border=w-w//3;train_width=border-p['buffer_cells'] if hold else w
    require(train_width>=1,'Spatial buffer excludes all training columns.')
    ok=np.isfinite(stack);train=ok.copy()
    if hold:train[cut:]=False;train[:,:,train_width:]=False
    ix=np.argwhere(train);require(len(ix)>=12,'At least twelve valid training observations required.')
    rng=np.random.default_rng(p['seed'])
    if len(ix)>p['sample_limit']:ix=ix[np.sort(rng.choice(len(ix),p['sample_limit'],replace=False))]
    def xyz(ids):
        a,b,c=ids.T;return np.column_stack(((c+.5)*grid.transform.a,(b+.5)*abs(grid.transform.e),t[a]-t[0]))
    predict,meta=fit(xyz(ix),stack[tuple(ix.T)],p)
    meta.update(seed=p['seed'],training_indices=ix.tolist(),interpretation='Separable exponential covariance with independent nugget; ordinary kriging, profiled sill and mean, optional training-only REML. Conditional observation SD includes nugget and mean estimation, not covariance parameter uncertainty.')
    out=np.full((h,w),np.nan);rows=[]
    if not hold:
        require(h*w*len(ix)**2<=80_000_000,'Kriging prediction work budget exceeded.')
        r,c=np.indices((h,w));target=np.column_stack(((c.ravel()+.5)*grid.transform.a,(r.ravel()+.5)*abs(grid.transform.e),np.full(h*w,t[-1]-t[0]+p['horizon'])))
        mu,sd=predict(target);out=(mu if kind=='st_kriging_mean' else sd).reshape(h,w)
        meta['forecast_time']=float(t[-1]+p['horizon'])
    else:
        test=ok.copy();test[:cut]=False;test[:,:,:border]=False;ids=np.argwhere(test)
        require(len(ids)>=4 and len(ids)*len(ix)**2<=80_000_000,'Joint holdout lacks support or exceeds work budget.')
        mu,sd=predict(xyz(ids));truth=stack[tuple(ids.T)];e=mu-truth;inside=abs(e)<=1.959963984540054*sd
        count=np.zeros((h,w),int);total=np.zeros((h,w));rr,cc=ids[:,1:].T
        np.add.at(count,(rr,cc),1)
        values=e*e if kind=='st_holdout_rmse' else inside.astype(float) if kind=='st_holdout_coverage' else e
        np.add.at(total,(rr,cc),values);np.divide(total,count,out=out,where=count>0)
        if kind=='st_holdout_rmse':out=np.sqrt(out)
        for j in np.unique(ids[:,0]):
            m=ids[:,0]==j;rows.append([float(t[j]),int(m.sum()),float(np.sqrt(np.mean(e[m]**2))),float(np.sqrt(np.mean((meta['training_mean']-truth[m])**2))),float(inside[m].mean()),float(e[m].mean())])
        meta.update(holdout_dates=p['holdout_dates'],spatial_holdout_start_column=border,training_end_column_exclusive=train_width,
          validation_pairs=len(ids),rmse=float(np.sqrt(np.mean(e**2))),empirical_95_coverage=float(inside.mean()),bias=float(e.mean()),
          validation='Future dates and contiguous spatial block excluded before sample selection, normalization and covariance fitting. Coverage descriptive; test observations are dependent.')
    return out,['time','pairs','kriging_rmse','training_mean_rmse','coverage_95','bias'],rows,meta
