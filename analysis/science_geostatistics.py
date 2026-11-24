"""Bounded geostatistical prediction and spatial-error inference.

The covariance model and error assumptions are explicit. Conditional prediction
uncertainty is not a confidence statement about estimated covariance parameters.
"""
import math
import numpy as np
from .science_raster import require,adjacency,sample_cells
from .science_models import coordinates,descriptive_moran
from terrain.studio_data import aligned_grids


def ordinary_kriging(grids,params,kind):
    template,observations=grids
    require(template.crs==observations.crs and template.transform==observations.transform
            and template.values.shape==observations.values.shape,'Kriging grids must match exactly.')
    require(bool(observations.unit),'Declare the observation physical unit.')
    valid=np.isfinite(template.values);known=np.isfinite(observations.values)
    require(np.all(~known|valid),'Observations must lie inside the target validity mask.')
    n=int(known.sum());m=int(valid.sum())
    require(3<=n<=500 and m*n*n<=120_000_000,'Kriging requires 3–500 observations and a bounded target-by-covariance workspace.')
    xy=coordinates(template,known);targets=coordinates(template,valid);y=observations.values[known]
    scale=params['range_m'];sill=params['sill'];nugget=params['nugget_ratio']
    # Exponential covariance with e-folding distance range_m; nugget is
    # independent observation noise, not part of the latent process variance.
    def cov(a,b):
        delta=a[:,None,:]-b[None,:,:]
        return np.exp(-np.hypot(delta[:,:,0],delta[:,:,1])/scale)
    c=cov(xy,xy)+nugget*np.eye(n)
    require(np.linalg.cond(c)<1e10,'Ill-conditioned covariance matrix; revise range or nugget.')
    inv=np.linalg.solve(c,np.eye(n));inv=(inv+inv.T)*.5
    one=inv.sum(axis=1);den=float(one.sum());require(den>0,'Invalid ordinary kriging constraint.')
    center=float(y.mean());alpha=inv@(y-center)
    correction=float(alpha.sum()/den);beta=alpha-one*correction
    pred=np.empty(m);variance=np.empty(m)
    for start in range(0,m,256):
        k=cov(targets[start:start+256],xy);a=k@one
        pred[start:start+len(k)]=center+correction+k@beta
        v=1-np.einsum('ij,ij->i',k@inv,k)+(1-a)**2/den
        require(np.min(v)>=-1e-7,'Kriging covariance calculation produced negative variance.')
        variance[start:start+len(k)]=np.maximum(v,0)*sill
    # Exact leave-one-out prediction of observed (possibly noisy) values from
    # the generalized precision matrix, with the mean re-estimated each time.
    precision=np.diag(inv)-one**2/den
    require(np.all(precision>0),'Invalid leave-one-out precision.')
    error=beta/precision;loo=y-error;loo_sd=np.sqrt(sill/precision)
    rows=[[float(a),float(b),float(o),float(p),float(e),float(s),float(e/s)]
          for (a,b),o,p,e,s in zip(xy,y,loo,error,loo_sd)]
    out=np.full(valid.shape,np.nan);out[valid]=pred if kind=='ordinary_kriging' else np.sqrt(variance)
    report={'observations':n,'prediction_cells':m,'covariance':'exponential','range_m':scale,
            'partial_sill':sill,'nugget_variance':sill*nugget,'loo_rmse':float(np.sqrt(np.mean(error**2))),
            'loo_mae':float(np.mean(abs(error))),'loo_mean_standardized_error':float(np.mean(error/loo_sd)),
            'loo_rms_standardized_error':float(np.sqrt(np.mean((error/loo_sd)**2))),
            'loo_gaussian_95_coverage':float(np.mean(abs(error)<=1.95996398454*loo_sd)),
            'interpretation':'Latent-process prediction with supplied covariance parameters and unknown constant mean. LOO evaluates observation prediction; no spatial-block or external validation, and no covariance-parameter uncertainty.'}
    return out,['easting','northing','observed','prediction','residual','prediction_sd','standardized_residual'],rows,report,observations.unit


def spatial_error_regression(grids,params,view):
    """Concentrated Gaussian ML for y=Xb+u, u=lambda W u+epsilon."""
    stack,valid=aligned_grids(grids,require_same_unit=False);g=grids[0]
    xy=coordinates(g,valid);y=stack[0,valid];raw=stack[1:,valid].T;n,p=raw.shape
    require(max(12,4*(p+1))<=n<=600,'Spatial error ML requires a bounded 12–600 complete cells and sufficient degrees of freedom.')
    scale=raw.std(axis=0);require(np.all(scale>0),'Predictors must vary.')
    mu=raw.mean(axis=0);x=np.column_stack((np.ones(n),(raw-mu)/scale))
    require(np.linalg.matrix_rank(x)==p+1,'Predictors are collinear.')
    _,i,j=adjacency(np.where(valid,g.values,np.nan));a=np.r_[i,j];b=np.r_[j,i]
    degree=np.bincount(a,minlength=n);require(np.all(degree>0),'Spatial error model requires no isolated complete-case cells.')
    # W is similar to the symmetric normalized adjacency, giving real
    # eigenvalues for an exact log determinant without dense determinants per fit.
    symmetric=np.zeros((n,n));symmetric[a,b]=1/np.sqrt(degree[a]*degree[b])
    eig=np.linalg.eigvalsh(symmetric)
    def lag(v):
        if v.ndim==1:return np.bincount(a,weights=v[b],minlength=n)/degree
        return np.column_stack([lag(v[:,j]) for j in range(v.shape[1])])
    center=float(y.mean());yc=y-center;ys=float(yc.std());require(ys>0,'Response must vary.')
    normalized=yc/ys;wy=lag(normalized);wx=lag(x)
    def evaluate(lam):
        design=x-lam*wx;target=normalized-lam*wy
        coef=np.linalg.lstsq(design,target,rcond=None)[0];e=target-design@coef
        variance=float(e@e/n)
        if variance<=1e-24:return -np.inf,coef,variance
        logdet=float(np.log1p(-lam*eig).sum())
        return logdet-.5*n*(math.log(2*math.pi)+1+math.log(variance)+2*math.log(ys)),coef,variance
    # Coarse global scan followed by bounded local golden-section refinement.
    bound=params['lambda_bound'];grid=np.linspace(-bound,bound,81)
    scores=np.array([evaluate(q)[0] for q in grid]);require(np.isfinite(scores).any(),'Degenerate spatial-error likelihood.')
    best=int(np.argmax(scores));lo=grid[max(0,best-1)];hi=grid[min(len(grid)-1,best+1)]
    ratio=(math.sqrt(5)-1)/2
    for _ in range(45):
        left=hi-ratio*(hi-lo);right=lo+ratio*(hi-lo)
        if evaluate(left)[0]>=evaluate(right)[0]:hi=right
        else:lo=left
    candidates=[float(grid[best]),float((lo+hi)/2)]
    lam=max(candidates,key=lambda q:evaluate(q)[0]);ll,coef,var=evaluate(lam)
    pred=center+ys*(x@coef);res=y-pred;innovation=res-lam*lag(res)
    # Report GLS coefficient standard errors conditional on the fitted lambda.
    design=x-lam*wx;cov=var*np.linalg.solve(design.T@design,np.eye(p+1))*ys**2
    require(np.all(np.diag(cov)>=0),'Invalid conditional coefficient covariance.')
    slopes=ys*coef[1:]/scale;se=np.sqrt(np.diag(cov)[1:])/scale
    out=np.full(valid.shape,np.nan);out[valid]=pred if view=='prediction' else res
    rgrid=np.full(valid.shape,np.nan);rgrid[valid]=res
    igrid=np.full(valid.shape,np.nan);igrid[valid]=innovation
    rows=[[float(a),float(b),float(c),float(d),float(e),float(f)]
          for (a,b),c,d,e,f in zip(xy,y,pred,res,innovation)]
    return out,['easting','northing','observed','prediction','residual','innovation'],rows,{
        'lambda':lam,'lambda_at_search_boundary':bool(abs(lam)>=bound-1e-6),'log_likelihood':ll,
        'aic':float(2*(p+3)-2*ll),'intercept':float(center+ys*coef[0]-slopes@mu),
        'coefficients':slopes.tolist(),'conditional_coefficient_se':se.tolist(),
        'innovation_variance':float(var*ys**2),'residual_moran_i':descriptive_moran(rgrid),
        'innovation_moran_i':descriptive_moran(igrid),'rmse':float(np.sqrt(np.mean(res**2))),
        'view':view,'interpretation':'Gaussian spatial error maximum likelihood with bounded rook W and constant variance innovations. Coefficient SE conditions on fitted lambda; fitted response is not held-out prediction.'}


def difference_probability(grids,rho,threshold):
    stack,valid=aligned_grids(grids);g=grids[0]
    require(bool(g.unit),'Declare matching physical units for all four inputs.')
    a,b,sa,sb=stack[:,valid];require(np.all(sa>=0) and np.all(sb>=0),'Standard uncertainties must be nonnegative.')
    sd=np.sqrt((sa-sb)**2+2*(1-rho)*sa*sb);delta=a-b-threshold
    positive=sd>0;v=np.empty(len(sd));v[~positive]=(delta[~positive]>0).astype(float)
    z=np.divide(delta[positive],sd[positive]);v[positive]=np.fromiter((.5*math.erfc(-float(q)/math.sqrt(2)) for q in z),float,count=len(z))
    out=np.full(valid.shape,np.nan);out[valid]=v
    return out,{'threshold':threshold,'correlation':rho,'deterministic_cells':int((~positive).sum()),
                'mean_probability':float(v.mean()),'interpretation':'Conditional Gaussian same-cell error model with supplied standard deviations and correlation; strict exceedance. No spatial joint probability or calibration implied.'}


def srs_estimation(grid,params):
    z=grid.values;count=params['count'];population=int(np.isfinite(z).sum())
    require(2<=count<=population,'Simple random estimation requires at least two observations.')
    idx,weights=sample_cells(z,'sample_random',count,params['seed']);values=z.flat[idx]
    mean=float(values.mean());sd=float(values.std(ddof=1));se=float(sd*np.sqrt((1-count/population)/count))
    row,col=np.unravel_index(idx,z.shape);xx,yy=grid.axes
    rows=[[int(r),int(c),float(xx[c]),float(yy[r]),float(v),float(w)] for r,c,v,w in zip(row,col,values,weights)]
    return ['row','column','x','y','value','design_weight'],rows,{
        'sample_count':count,'population_count':population,'mean_estimate':mean,
        'total_estimate':mean*population,'mean_standard_error':se,'total_standard_error':se*population,
        'normal_95_mean_interval':[mean-1.95996398454*se,mean+1.95996398454*se],
        'interpretation':'SRS without replacement, finite population correction; normal interval is approximate and may be unreliable for small or skewed samples.'}
