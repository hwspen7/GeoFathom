"""Bounded extreme-value likelihood fits and observed space-time event components."""
import numpy as np
from scipy.optimize import minimize
from scipy.ndimage import label,generate_binary_structure
from analysis.science_raster import require

def fit_gpd(excess):
    scale=float(np.mean(excess));require(scale>0,'Positive excess required.')
    x=excess/scale
    def nll(a):
        shape,logscale=a;s=np.exp(logscale);z=x/s;u=1+shape*z
        if np.any(u<=0):return 1e30
        term=z if abs(shape)<1e-7 else (1+1/shape)*np.log1p(shape*z)
        return float(len(x)*logscale+term.sum())
    fit=minimize(nll,[0.,0.],method='Powell',bounds=[(-.4,.4),(-6,6)],options={'maxiter':100,'xtol':1e-7,'ftol':1e-9})
    if not fit.success or fit.fun>=1e29 or fit.fun>nll([0.,0.])+1e-6:return None
    return float(fit.x[0]),float(scale*np.exp(fit.x[1])),bool(abs(fit.x[0])>.3999 or abs(fit.x[1])>5.999)

def fit_gev(maxima):
    center=float(maxima.mean());scale=float(maxima.std())
    if not scale>0:return None
    x=(maxima-center)/scale
    def nll(a):
        shape,loc,logscale=a;s=np.exp(logscale);z=(x-loc)/s;u=1+shape*z
        if np.any(u<=0):return 1e30
        v=z if abs(shape)<1e-7 else np.log1p(shape*z)/shape
        if np.any(-v>700):return 1e30
        return float(len(x)*logscale+np.sum((1+shape)*v+np.exp(-v)))
    start=[0.,-.4,0.]
    fit=minimize(nll,start,method='Powell',bounds=[(-.4,.4),(-5,5),(-6,6)],options={'maxiter':150,'xtol':1e-7,'ftol':1e-9})
    if not fit.success or fit.fun>=1e29 or fit.fun>nll(start)+1e-6:return None
    shape,loc,ls=fit.x
    return float(shape),float(center+scale*loc),float(scale*np.exp(ls)),bool(abs(shape)>.3999 or abs(loc)>4.999 or abs(ls)>5.999)

def bootstrap_interval(samples,gev,threshold,period,minimum,replicates,seed):
    """Parametric stationary iid bootstrap, including the GPD occurrence rate."""
    from scipy.stats import genextreme,genpareto
    rng=np.random.default_rng(seed);values=[];bound=0
    if gev:
        fitted=fit_gev(samples)
        if fitted is None:return None
        xi,mu,sigma,_=fitted
    else:
        excess=samples[samples>threshold]-threshold
        if len(excess)<minimum or len(excess)==len(samples):return None
        fitted=fit_gpd(excess)
        if fitted is None:return None
        xi,sigma,_=fitted;rate=len(excess)/len(samples)
        if period*rate<=1:return None
    for _ in range(replicates):
        if gev:
            simulated=genextreme.rvs(-xi,loc=mu,scale=sigma,size=len(samples),random_state=rng)
            f=fit_gev(simulated)
            if f is None:continue
            s,l,v,b=f;level=float(genextreme.ppf(1-1/period,-s,loc=l,scale=v))
        else:
            count=int(rng.binomial(len(samples),rate))
            if count<minimum or count==len(samples) or period*count/len(samples)<=1:continue
            simulated=genpareto.rvs(xi,scale=sigma,size=count,random_state=rng)
            f=fit_gpd(simulated)
            if f is None:continue
            s,v,b=f;level=float(threshold+genpareto.isf(1/(period*count/len(samples)),s,scale=v))
        if np.isfinite(level):values.append(level);bound+=int(b)
    if len(values)<max(30,int(np.ceil(.8*replicates))):return None
    low,high=np.quantile(values,[.025,.975])
    return float(low),float(high),len(values),bound

def extreme_interval(stack,t,p,kind):
    n,h,w=stack.shape;B=p['bootstrap_replicates'];gev=kind.startswith('gev_')
    require(h*w*B<=1600,'Bootstrap limited to small study windows; reduce crop or replicates.')
    require(np.allclose(np.diff(t),np.diff(t)[0],rtol=1e-7,atol=1e-10),'Extremes require a regular time axis.')
    out=np.full((h,w),np.nan);counts=[];bound=0;minimum=p['extreme_minimum'];block=p.get('block_length',1)
    for i,j in np.ndindex(h,w):
        y=stack[:,i,j]
        if gev:
            a=y[:n//block*block].reshape(-1,block);a=a[np.isfinite(a).all(axis=1)]
            samples=a.max(axis=1) if len(a) else np.empty(0)
        else:samples=y[np.isfinite(y)]
        if len(samples)<minimum:continue
        interval=bootstrap_interval(samples,gev,p.get('threshold',0.),p['return_period'],minimum,B,np.random.SeedSequence([p['seed'],i,j]))
        if interval is None:continue
        low,high,count,b=interval;counts.append(count);bound+=b
        out[i,j]=low if kind.endswith('_low') else high
    return out,{'bootstrap_replicates':B,'supported_cells':len(counts),'minimum_successful_refits':min(counts) if counts else 0,'boundary_refits':bound,'confidence_level':.95,'interpretation':'Pointwise percentile parametric bootstrap of the fitted stationary iid model, with bounded likelihood refits and binomial occurrence uncertainty for GPD. No spatial simultaneous coverage, no declustering, no correction for serial dependence or model misspecification. Failed refits above 20% invalidate the cell; boundary estimates can distort intervals.'}

def extremes(stack,t,p,kind):
    n,h,w=stack.shape;require(n*h*w<=16000,'Extreme value likelihood budget exceeded.')
    require(np.allclose(np.diff(t),np.diff(t)[0],rtol=1e-7,atol=1e-10),'Extremes need regular dates; use explicit complete blocks.')
    gev=kind.startswith('gev_');out=np.full((h,w),np.nan);fits=0;bound=0;threshold=p.get('threshold');block=p.get('block_length',1);R=p['return_period']
    if gev:require(n//block>=p['minimum_observations'] and R>1,'Insufficient complete blocks or invalid return period.')
    for i,j in np.ndindex(h,w):
        y=stack[:,i,j]
        if gev:
            a=y[:n//block*block].reshape(-1,block);maxima=a[np.isfinite(a).all(axis=1)].max(axis=1)
            if len(maxima)<p['minimum_observations']:continue
            fit=fit_gev(maxima)
            if fit is None:continue
            xi,mu,sigma,atbound=fit;v=-np.log(-np.log1p(-1/R))
            level=mu+sigma*(v if abs(xi)<1e-7 else np.expm1(xi*v)/xi)
        else:
            good=np.isfinite(y);v=y[good]-threshold;x=v[v>0]
            if len(x)<p['minimum_observations'] or len(x)==len(v):continue
            fit=fit_gpd(x)
            if fit is None:continue
            xi,sigma,atbound=fit;rate=len(x)/len(v);a=R*rate
            # Return level is above threshold only if its target tail
            # probability is smaller than the empirical exceedance frequency.
            if a<=1 and not kind.endswith('_shape'):continue
            level=threshold+sigma*(np.log(a) if abs(xi)<1e-7 else np.expm1(xi*np.log(a))/xi) if a>1 else np.nan
        fits+=1;bound+=atbound
        out[i,j]=xi if kind.endswith('_shape') else level
    return out,{'fitted_cells':fits,'boundary_fits':bound,'return_period':R,'return_period_unit':'complete observation blocks' if gev else 'valid acquisition opportunities',
      'interpretation':'Bounded numerical maximum likelihood (shape [-0.4,0.4]); assumes stationary independent block maxima or independent threshold excesses. GPD uses empirical exceedance fraction, no declustering or correction for informative missingness. Return period in blocks/acquisitions, not calendar years; no confidence interval. Boundary estimates and small samples require caution.'}

def track(stack,t,grid,p,kind):
    n,h,w=stack.shape;require(grid.is_meter,'Event area requires projected metre grid.')
    require(n*h*w<=1_000_000,'Space-time connected-component budget exceeded.')
    valid=np.isfinite(stack);active=valid&(stack>p['threshold']);out=np.full((h,w),np.nan)
    out[valid.any(axis=0)]=0
    # Six-neighbor connectivity; a temporal edge requires same-cell
    # overlap at adjacent dates. Gaps split cubes, never bridge missing cells.
    cuts=np.r_[0,np.flatnonzero(np.diff(t)>p['maximum_gap'])+1,n]
    cell_area=abs(grid.transform.a*grid.transform.e);events=[];next_id=1
    latest=np.zeros((h,w),int);spanmap=np.zeros((h,w));peakmap=np.zeros((h,w))
    for a,b in zip(cuts,cuts[1:]):
        labels,k=label(active[a:b],structure=generate_binary_structure(3,1))
        require(next_id+k<=10001,'Event component count exceeds 10,000.')
        # Group occupied voxels once, rather than rescanning for every event.
        ids=np.argwhere(labels>0);keys=labels[tuple(ids.T)]
        order=np.argsort(keys,kind='stable');ids=ids[order];keys=keys[order]
        splits=np.r_[0,np.flatnonzero(np.diff(keys))+1,len(keys)]
        for lo,hi in zip(splits,splits[1:]):
            if lo==hi:continue
            z=ids[lo:hi];tt,rr,cc=z.T;tt=tt+a
            if len(z)<p['minimum_voxels']:continue
            dates,cnt=np.unique(tt,return_counts=True);span=float(t[dates[-1]]-t[dates[0]])
            peak=float(cnt.max()*cell_area);footprint=len(np.unique(np.column_stack((rr,cc)),axis=0))*cell_area
            events.append([next_id,float(t[dates[0]]),float(t[dates[-1]]),len(dates),len(z),span,peak,float(footprint)])
            np.maximum.at(spanmap,(rr,cc),span);np.maximum.at(peakmap,(rr,cc),peak)
            end=tt==n-1;latest[rr[end],cc[end]]=next_id;next_id+=1
    if kind=='tracked_latest_id':out[valid[-1]]=latest[valid[-1]];out[~valid[-1]]=np.nan
    else:out[valid.any(axis=0)]=(spanmap if kind=='tracked_span' else peakmap)[valid.any(axis=0)]
    return out,['event','first_time','last_time','dates','voxels','span','peak_area_m2','footprint_m2'],events,{'events':len(events),'interpretation':'Six-connected observed exceedance voxels, temporal adjacency only at same cell and within maximum gap. Connected components may merge/split into one event family; no identity tracking across nonoverlap or missing data. Area is planar projected cell area, span is observed first-to-last time.'}
