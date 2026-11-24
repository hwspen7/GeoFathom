"""Conditional physical corrections, robust multivariate change and time-series inference."""
import math
import numpy as np
from analysis.science_raster import require

def atmospheric_reflectance(v):
    # Lambertian model: TOA = path + transmission * surface/(1-albedo*surface).
    y=v['toa']-v['path'];t=v['transmission'];s=v['spherical_albedo']
    den=t+s*y;out=np.full(y.shape,np.nan)
    good=np.isfinite(den)&(den>0)&np.isfinite(y)
    out[good]=y[good]/den[good]
    invalid=np.isfinite(out)&((out<-.2)|(out>1.6))
    out[invalid]=np.nan
    return out,{'outside_supported_reflectance':int(invalid.sum()),'model':'Lambertian scalar atmospheric inversion with externally supplied coefficients; no atmospheric retrieval.'}

def robust_harmonization(v,p):
    x=v['candidate'];y=v['reference'];train=np.isfinite(x)&np.isfinite(y)&(v['calibration']==1)
    require(train.sum()>=20,'At least twenty stable paired calibration cells required.')
    a=x[train];b=y[train];design=np.column_stack((np.ones(len(a)),a))
    require(np.linalg.cond(design)<1e8,'Calibration reflectance variation is insufficient.')
    coef=np.linalg.lstsq(design,b,rcond=None)[0];converged=False
    for i in range(p['iterations']):
        residual=b-design@coef;scale=1.4826*np.median(abs(residual-np.median(residual)))
        if scale<1e-12:
            # Exact inliers: retain a numerical floor rather than giving outliers full weight.
            scale=1e-12
        weight=np.minimum(1,p['huber_k']*scale/np.maximum(abs(residual),1e-30))
        root=np.sqrt(weight);new=np.linalg.lstsq(design*root[:,None],b*root,rcond=None)[0]
        if np.linalg.norm(new-coef)<=1e-9*(1+np.linalg.norm(coef)):
            coef=new;converged=True;break
        coef=new
    require(converged and coef[1]>0,'Robust radiometric fit did not converge to a positive gain.')
    out=coef[0]+coef[1]*x;invalid=np.isfinite(out)&((out<-.2)|(out>1.6));out[invalid]=np.nan
    hold=(v['calibration']==2)&np.isfinite(x)&np.isfinite(y)
    error=b-design@coef
    return out,{'gain':float(coef[1]),'offset':float(coef[0]),'iterations':i+1,'calibration_cells':int(train.sum()),
                'calibration_median_absolute_error':float(np.median(abs(error))),
                'heldout_cells':int(hold.sum()),'heldout_rmse':float(np.sqrt(np.mean((coef[0]+coef[1]*x[hold]-y[hold])**2))) if hold.any() else None,
                'excluded_out_of_range':int(invalid.sum()),'interpretation':'Empirical robust normalization; mask 1 fits, mask 2 evaluates without fitting.'}

def irmad(v,p):
    a=np.stack([v[k+'_before'] for k in ('red','nir','swir')]);b=np.stack([v[k+'_after'] for k in ('red','nir','swir')])
    valid=np.isfinite(a).all(axis=0)&np.isfinite(b).all(axis=0)
    x=a[:,valid].T;y=b[:,valid].T;n=len(x)
    require(30<=n<=100000 and n*p['iterations']<=6_000_000,'IR-MAD requires 30–100,000 complete cells within iteration budget.')
    weight=np.ones(n);previous=None;history=[];converged=False
    for i in range(p['iterations']):
        mass=float(weight.sum());ess=mass**2/float(weight@weight)
        require(ess>=12,'IR-MAD effective sample size is insufficient.')
        mx=weight@x/mass;my=weight@y/mass;xc=x-mx;yc=y-my
        def white(z):
            c=(z*weight[:,None]).T@z/mass;e,q=np.linalg.eigh(c)
            require(e[-1]>0 and e[0]>e[-1]*1e-9,'IR-MAD covariance is rank deficient.')
            return (q/np.sqrt(e))@q.T
        wx=white(xc);wy=white(yc);cross=((xc@wx)*weight[:,None]).T@(yc@wy)/mass
        u,rho,vt=np.linalg.svd(cross,full_matrices=False)
        require(np.all(rho<1-1e-10),'IR-MAD canonical correlations are degenerate.')
        delta=xc@wx@u-yc@wy@vt.T
        distance=np.sum(delta**2/(2*(1-rho)),axis=1)
        # Exact chi-square(3) survival function; weights are not calibrated change probabilities.
        root=np.sqrt(distance/2)
        next_weight=np.fromiter((math.erfc(float(q)) for q in root),float,count=n)+2/math.sqrt(math.pi)*root*np.exp(-root**2)
        next_weight=np.clip(next_weight,0,1)
        change=float(np.max(abs(rho-previous))) if previous is not None else None
        history.append([i+1,ess,*rho.tolist(),change])
        if change is not None and change<=p['tolerance']:
            converged=True;break
        previous=rho;weight=next_weight
    out=np.full(valid.shape,np.nan);out[valid]=distance
    return out,['iteration','effective_sample_size','rho1','rho2','rho3','max_correlation_change'],history,{
        'converged':converged,'iterations':i+1,'canonical_correlations':rho.tolist(),'effective_sample_size':ess,
        'interpretation':'Iteratively reweighted canonical alteration statistic; nonconverged result is diagnostic only; spatial dependence and mixture assumptions prevent calibrated p-value claims.'}

def cloud_buffer(z,radius):
    # Disk dilation of cloud/invalid surroundings. Original NoData is retained.
    require(z.size*(2*radius+1)**2<=80_000_000,'Cloud buffer exceeds neighborhood work budget.')
    valid=np.isfinite(z);require(np.all(np.isin(z[valid],[0,1])),'Binary mask requires 0 or 1.')
    bad=~valid|(z==0);h,w=z.shape;pad=np.pad(bad,radius,constant_values=False);expanded=np.zeros(z.shape,bool)
    for dy in range(-radius,radius+1):
        for dx in range(-radius,radius+1):
            if dx*dx+dy*dy<=radius*radius:expanded|=pad[radius+dy:radius+dy+h,radius+dx:radius+dx+w]
    return np.where(valid,(~expanded).astype(float),np.nan),{'radius_cells':radius,'newly_excluded_cells':int((valid&(z==1)&expanded).sum())}

def series_break(stack,times,min_segment,kind):
    t=np.asarray(times,float);n,h,w=stack.shape
    require(len(t)==n and np.isfinite(t).all() and np.all(np.diff(t)>0),'Times must be strictly increasing.')
    require(n>=2*min_segment and n*h*w<=2_000_000,'Breakpoint work budget or minimum segment requirement exceeded.')
    # One change in mean: exact least squares scan, excluding missing observations.
    valid=np.isfinite(stack);count=valid.sum(axis=0)
    mean=np.divide(np.nansum(stack,axis=0),count,out=np.zeros((h,w)),where=count>0)
    y=np.where(valid,stack-mean,0);cs=np.cumsum(y,axis=0);cn=np.cumsum(valid,axis=0)
    total=cs[-1];base=np.sum(y*y,axis=0)-np.divide(total**2,count,out=np.zeros((h,w)),where=count>0)
    best=np.full((h,w),-np.inf);when=np.full((h,w),np.nan);jump=np.full((h,w),np.nan)
    for k in range(1,n):
        l=cn[k-1];r=count-l;ok=(l>=min_segment)&(r>=min_segment)&valid[k-1]&valid[k]
        ml=np.divide(cs[k-1],l,out=np.zeros((h,w)),where=l>0);mr=np.divide(total-cs[k-1],r,out=np.zeros((h,w)),where=r>0)
        improvement=np.divide(l*r,count,out=np.zeros((h,w)),where=count>0)*(mr-ml)**2
        update=ok&(improvement>best);best[update]=improvement[update];when[update]=t[k-1]+(t[k]-t[k-1])/2;jump[update]=(mr-ml)[update]
    good=np.isfinite(best)&(base>0);out=np.full((h,w),np.nan)
    if kind=='series_break_time':out[good]=when[good]
    elif kind=='series_break_jump':out[good]=jump[good]
    else:out[good]=np.clip(best[good]/base[good],0,1)
    return out,{'acquisitions':n,'times':times,'min_segment':min_segment,'model':'Single mean shift, exhaustive least-squares split; no significance test; gaps adjacent to split excluded.'}
