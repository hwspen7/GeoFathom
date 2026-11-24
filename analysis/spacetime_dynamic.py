"""Retrospective RTS smoothing and pooled conditional likelihood estimation."""
import numpy as np
from scipy.optimize import minimize
from analysis.science_raster import require

def filter_series(y,t,q,r,v):
    n=len(y);first=int(np.flatnonzero(np.isfinite(y))[0])
    mf=np.full((n,2),np.nan);pf=np.full((n,2,2),np.nan)
    mp=mf.copy();pp=pf.copy();trans=pf.copy()
    mf[first]=[y[first],0.];pf[first]=np.diag([r,v]);loss=0.;count=0
    for i in range(first+1,n):
        dt=t[i]-t[i-1];F=np.array([[1.,dt],[0.,1.]])
        Q=q*np.array([[dt**3/3,dt**2/2],[dt**2/2,dt]])
        trans[i]=F;mp[i]=F@mf[i-1];pp[i]=F@pf[i-1]@F.T+Q
        mf[i]=mp[i];pf[i]=pp[i]
        if np.isfinite(y[i]):
            e=y[i]-mp[i,0];s=pp[i,0,0]+r
            require(np.isfinite(s) and s>0,'Nonfinite innovation variance.')
            loss+=.5*(np.log(2*np.pi*s)+e*e/s);count+=1
            g=pp[i,:,0]/s;mf[i]+=g*e;A=np.eye(2)-np.outer(g,[1.,0.])
            pf[i]=A@pp[i]@A.T+r*np.outer(g,g);pf[i]=(pf[i]+pf[i].T)/2
    return mf,pf,mp,pp,trans,first,loss,count

def smooth(y,t,q,r,v):
    mf,pf,mp,pp,F,first,loss,count=filter_series(y,t,q,r,v)
    ms=mf.copy();ps=pf.copy()
    for i in range(len(t)-2,first-1,-1):
        G=np.linalg.solve(pp[i+1],F[i+1]@pf[i]).T
        ms[i]=mf[i]+G@(ms[i+1]-mp[i+1]);ps[i]=pf[i]+G@(ps[i+1]-pp[i+1])@G.T
        ps[i]=(ps[i]+ps[i].T)/2
        require(np.min(np.linalg.eigvalsh(ps[i]))>=-1e-9*max(1.,np.max(abs(pf[i]))),'Invalid smoothed covariance.')
    return ms,ps

def estimate(stack,t,p):
    n,h,w=stack.shape;cut=n-p['holdout_dates'];require(cut>=6,'At least six training dates before holdout.')
    train=stack[:cut].reshape(cut,-1);ids=np.flatnonzero(np.isfinite(train).sum(axis=0)>=p['minimum_observations'])
    require(len(ids)>=1,'No eligible training trajectories.')
    rng=np.random.default_rng(p['seed'])
    if len(ids)>p['trajectory_limit']:ids=np.sort(rng.choice(ids,p['trajectory_limit'],replace=False))
    data=train[:,ids];q,r,v=(p[k] for k in ('process_variance','observation_variance','initial_velocity_variance'))
    start=np.log([q,r])
    def objective(z):
        qq,rr=np.exp(z);total=0.;count=0
        for y in data.T:
            *_,loss,k=filter_series(y,t[:cut],qq,rr,v);total+=loss;count+=k
        return total/count
    initial=objective(start)
    opt=minimize(objective,start,method='L-BFGS-B',bounds=[(z-9.21,z+9.21) for z in start],options={'maxiter':80,'maxfun':300,'ftol':1e-9})
    require(opt.success and opt.fun<=initial+1e-8,'Conditional likelihood fit did not converge.')
    q,r=np.exp(opt.x)
    return float(q),float(r),{'training_end_exclusive':cut,'training_trajectory_indices':ids.tolist(),'initial_nll_per_observation':float(initial),'fitted_nll_per_observation':float(opt.fun),'process_variance':float(q),'observation_variance':float(r),'fit_at_bound':bool(np.any(abs(opt.x-start)>9.209))}

def dynamic(stack,t,p,kind):
    n,h,w=stack.shape;require(n*h*w<=100000,'RTS work budget exceeded.')
    q,r,v=(p[k] for k in ('process_variance','observation_variance','initial_velocity_variance'))
    fitted=kind.startswith('fitted_');meta={}
    if fitted:q,r,meta=estimate(stack,t,p)
    cut=n-p.get('holdout_dates',0);index=p.get('target_date',1)-1
    require(fitted or 0<=index<n,'Target date outside cube.')
    out=np.full((h,w),np.nan);sq=np.zeros(n);base=np.zeros(n);num=np.zeros(n,int)
    for i,j in np.ndindex(h,w):
        y=stack[:,i,j];training=y[:cut] if fitted else y
        if np.isfinite(training).sum()<p['minimum_observations']:continue
        if fitted:
            # Forecast all holdout observations from one fixed training origin.
            mf,pf,*_=filter_series(training,t[:cut],q,r,v);last=training[np.flatnonzero(np.isfinite(training))[-1]]
            dt=t[cut:]-t[cut-1];pred=mf[-1,0]+dt*mf[-1,1]
            ok=np.isfinite(y[cut:]);e=pred[ok]-y[cut:][ok];b=last-y[cut:][ok]
            if len(e):
                ids=np.flatnonzero(ok)+cut;sq[ids]+=e*e;base[ids]+=b*b;num[ids]+=1
                out[i,j]=np.sqrt(np.mean(e*e)) if kind=='fitted_state_rmse' else (1-np.sum(e*e)/np.sum(b*b) if np.sum(b*b)>0 else np.nan)
        else:
            ms,ps=smooth(y,t,q,r,v)
            if kind=='rts_level':out[i,j]=ms[index,0]
            elif kind=='rts_velocity':out[i,j]=ms[index,1]
            else:out[i,j]=np.sqrt(max(0.,ps[index,0,0])) if np.isfinite(ps[index,0,0]) else np.nan
    rows=[[float(t[i]),int(num[i]),float(np.sqrt(sq[i]/num[i])),float(np.sqrt(base[i]/num[i]))] for i in np.flatnonzero(num)]
    meta.update(interpretation='Pooled conditional innovation likelihood fits shared process/observation variance on earlier dates only; holdout forecast never updates on test observations.' if fitted else 'RTS retrospective conditional latent-state smoothing uses subsequent observations intentionally; not a forecast or validation. Before the first valid observation is NoData.',target_time=None if fitted else float(t[index]))
    return out,['time','pairs','state_rmse','persistence_rmse'],rows,meta
