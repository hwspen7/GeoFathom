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
    universal=bool(p.get('universal',0));interaction=p.get('interaction',0.)
    origin=x.mean(axis=0);spread=x.std(axis=0)
    require(not universal or np.all(spread>0),'Universal drift needs variation along both spatial axes and time.')
    def design(a):return np.column_stack((np.ones(len(a)),(a-origin)/spread)) if universal else np.ones((len(a),1))
    H=design(x);rank=H.shape[1];require(np.linalg.matrix_rank(H)==rank,'Rank deficient drift design.')
    # Gneiting class: spatial dimension two, exponential spatial kernel,
    # temporal variogram |tau| and interaction in [0,1].
    def correlation(ds,dt,rs,rt,interaction):
        if 'interaction' not in p:return np.exp(-ds/rs-dt/rt)
        u=1+dt/rt;return np.exp(-ds/rs/u**(interaction/2))/u**interaction
    def model(theta):
        rs,rt,ratio=np.exp(theta[:3]);b=float(theta[3]) if len(theta)==4 else interaction
        K=correlation(ds,dt,rs,rt,b)+ratio*np.eye(len(z))
        factor=cho_factor(K,lower=True,check_finite=True)
        u=cho_solve(factor,H);normal=H.T@u;drift_factor=cho_factor(normal,lower=True)
        beta=cho_solve(drift_factor,u.T@z)
        residual=z-H@beta;alpha=cho_solve(factor,residual)
        sill=float(residual@alpha/(len(z)-rank))
        require(np.isfinite(sill) and sill>0,'Degenerate covariance fit.')
        objective=(len(z)-rank)*np.log(sill)+2*np.log(np.diag(factor[0])).sum()+2*np.log(np.diag(drift_factor[0])).sum()
        return objective,(rs,rt,ratio,factor,u,drift_factor,beta,alpha,sill,b)
    init=np.log([p['spatial_range'],p['temporal_range'],p['nugget_ratio']])
    tune=bool(p.get('fit_interaction',0))
    require(not tune or ('interaction' in p and p['fit_covariance']),'Interaction fitting requires Gneiting REML.')
    initial_objective=float(model(init)[0]);starts=0
    if p['fit_covariance']:
        require(len(x)<=256,'REML fitting limited to 256 training samples.')
        bounds=[(v-np.log(10),v+np.log(10)) for v in init]
        if tune:bounds.append((.05,1.))
        guesses=[np.r_[init,b] for b in sorted(set([interaction,.1,.9]))] if tune else [init]
        candidates=[]
        for guess in guesses:
            result=minimize(lambda a:model(a)[0],guess,method='L-BFGS-B',bounds=bounds,options={'maxiter':120,'maxfun':800,'ftol':1e-9})
            if result.success and np.isfinite(result.fun):candidates.append(result)
        starts=len(guesses);require(candidates,'REML covariance optimization failed; revise starting scales or use fixed ranges.')
        best=min(candidates,key=lambda a:a.fun);require(best.fun<=initial_objective+1e-7,'REML fit failed to improve initial likelihood.')
        theta=best.x
        boundary=bool(any(min(abs(v-lo),abs(v-hi))<1e-4 for v,(lo,hi) in zip(theta,bounds)))
    else:theta=init;boundary=False
    obj,(rs,rt,ratio,factor,u,drift_factor,beta,alpha,sill,selected_interaction)=model(theta)
    def predict(target):
        mu=[];sd=[]
        for i in range(0,len(target),256):
            v=target[i:i+256]
            cross=correlation(cdist(x[:,:2],v[:,:2]),cdist(x[:,2:],v[:,2:]),rs,rt,selected_interaction)
            solved=cho_solve(factor,cross);D=design(v).T-u.T@cross
            variance=1+ratio-np.sum(cross*solved,axis=0)+np.sum(D*cho_solve(drift_factor,D),axis=0)
            require(np.min(variance)>=-1e-8,'Invalid kriging variance.')
            mu.extend(center+scale*(design(v)@beta+cross.T@alpha));sd.extend(scale*np.sqrt(sill*np.maximum(variance,0)))
        return np.asarray(mu),np.asarray(sd)
    return predict,{'spatial_range':float(rs),'temporal_range':float(rt),'nugget_ratio':float(ratio),'sill':float(sill*scale**2),'reml_objective':float(obj),'fit_at_bound':boundary,
        'covariance_fitted':bool(p['fit_covariance']),'training_mean':center,'training_samples':len(x),'drift_rank':rank,'covariance_family':'Gneiting' if 'interaction' in p else 'separable exponential','interaction':selected_interaction,'interaction_fitted':tune,'initial_reml_objective':initial_objective,'optimization_starts':starts}

def kriging(stack,t,grid,p,kind):
    n,h,w=stack.shape
    require(grid.is_meter,'Kriging requires projected metre coordinates.')
    hold='holdout' in kind;cut=n-p.get('holdout_dates',0)
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
    meta.update(seed=p['seed'],training_indices=ix.tolist(),interpretation='Covariance family and drift rank recorded; profiled sill, optional training-only REML. Conditional observation SD includes nugget and drift estimation, not covariance parameter uncertainty.')
    out=np.full((h,w),np.nan);rows=[]
    if not hold:
        require(h*w*len(ix)**2<=80_000_000,'Kriging prediction work budget exceeded.')
        r,c=np.indices((h,w));target=np.column_stack(((c.ravel()+.5)*grid.transform.a,(r.ravel()+.5)*abs(grid.transform.e),np.full(h*w,t[-1]-t[0]+p['horizon'])))
        mu,sd=predict(target);out=(mu if kind.endswith('_mean') else sd).reshape(h,w)
        meta['forecast_time']=float(t[-1]+p['horizon'])
    else:
        test=ok.copy();test[:cut]=False;test[:,:,:border]=False;ids=np.argwhere(test)
        require(len(ids)>=4 and len(ids)*len(ix)**2<=80_000_000,'Joint holdout lacks support or exceeds work budget.')
        mu,sd=predict(xyz(ids));truth=stack[tuple(ids.T)];e=mu-truth;inside=abs(e)<=1.959963984540054*sd
        count=np.zeros((h,w),int);total=np.zeros((h,w));rr,cc=ids[:,1:].T
        np.add.at(count,(rr,cc),1)
        values=e*e if kind.endswith('_rmse') else inside.astype(float) if kind.endswith('_coverage') else e
        np.add.at(total,(rr,cc),values);np.divide(total,count,out=out,where=count>0)
        if kind.endswith('_rmse'):out=np.sqrt(out)
        for j in np.unique(ids[:,0]):
            m=ids[:,0]==j;rows.append([float(t[j]),int(m.sum()),float(np.sqrt(np.mean(e[m]**2))),float(np.sqrt(np.mean((meta['training_mean']-truth[m])**2))),float(inside[m].mean()),float(e[m].mean())])
        meta.update(holdout_dates=p['holdout_dates'],spatial_holdout_start_column=border,training_end_column_exclusive=train_width,
          validation_pairs=len(ids),rmse=float(np.sqrt(np.mean(e**2))),empirical_95_coverage=float(inside.mean()),bias=float(e.mean()),
          validation='Future dates and contiguous spatial block excluded before sample selection, normalization and covariance fitting. Coverage descriptive; test observations are dependent.')
    return out,['time','pairs','kriging_rmse','training_mean_rmse','coverage_95','bias'],rows,meta
