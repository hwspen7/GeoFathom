"""Advanced spatial models with explicit geometry, assumptions and work bounds."""
import numpy as np
from .science_raster import require, adjacency


def coordinates(grid, valid):
    require(grid.is_meter, 'Spatial distances require a projected metre raster.')
    row,col=np.nonzero(valid);x,y=grid.axes
    return np.column_stack((x[col],y[row]))


def weighted_edges(coords, mode, distance, power, k):
    """Bounded exact point graph. KNN ties use row-major observation order."""
    n=len(coords)
    require(3<=n<=3000 and n*n<=9_000_000,'Distance graph requires 3–3,000 valid cells; aggregate or crop explicitly.')
    require(mode!='knn' or k<n,'KNN requires fewer neighbors than observations.')
    source=[];target=[];weight=[]
    for start in range(0,n,128):
        ids=np.arange(start,min(start+128,n))
        delta=coords[ids,None,:]-coords[None,:,:]
        d=np.hypot(delta[:,:,0],delta[:,:,1])
        d[np.arange(len(ids)),ids]=np.inf
        if mode=='knn':
            j=np.argsort(d,axis=1,kind='stable')[:,:k].ravel()
            i=np.repeat(np.arange(len(ids)),k)
        else:
            i,j=np.nonzero(d<=distance)
        require(sum(len(a) for a in source)+len(i)<=1_000_000,'Spatial graph exceeds one million directed edges.')
        require(np.all(d[i,j]>0),'Distinct metric cell centers required.')
        source.append(ids[i]);target.append(j);weight.append(d[i,j])
    a,b,dist=map(np.concatenate,(source,target,weight))
    require(len(a)>0,'No neighbors at the specified distance.')
    # Relative distances avoid overflow and preserve inverse-distance ratios.
    w=(dist.min()/dist)**power if power else np.ones_like(dist)
    total=np.bincount(a,weights=w,minlength=n)
    require(np.all(total[a]>0) and np.all(w>0),'Distance weights exceed representable precision.')
    return a,b,w/total[a]


def weighted_moran(grid,params,mode):
    valid=np.isfinite(grid.values);coords=coordinates(grid,valid);v=grid.values[valid];n=len(v)
    a,b,w=weighted_edges(coords,mode,params.get('distance_m',1),params['power'],params.get('k',1))
    require((n+len(a))*(params['permutations']+1)<=30_000_000,'Weighted permutation work budget exceeded.')
    u=v-v.mean();ss=u@u;require(ss>0,'Moran statistic undefined for constant data.')
    def statistic(x):return float(n*np.dot(w,x[a]*x[b])/(w.sum()*ss))
    obs=statistic(u);expected=-1/(n-1);rng=np.random.default_rng(params['seed'])
    null=np.array([statistic(rng.permutation(u)) for _ in range(params['permutations'])])
    p=(1+np.count_nonzero(abs(null-expected)>=abs(obs-expected)-1e-14))/(len(null)+1)
    degree=np.bincount(a,minlength=n)
    return {'observed':obs,'expected':expected,'p_two_sided':float(p),'null_mean':float(null.mean()),
            'null_sd':float(null.std(ddof=1)),'directed_edges':len(a),'isolated_cells':int((degree==0).sum()),
            'valid_cells':n,'weight_definition':'row-standardized inverse distance','minimum_p':1/(len(null)+1),
            'permutations':len(null)},null


def descriptive_moran(z):
    v,a,b=adjacency(z);n=len(v)
    if n<3 or not len(a):return None
    u=v-v.mean();ss=u@u
    return float(n*np.dot(u[a],u[b])/(len(a)*ss)) if ss>0 else None


def multiscale(grid,max_factor):
    z=grid.values;h,w=z.shape;rows=[];total=int(np.isfinite(z).sum())
    require(grid.is_meter,'Multiscale analysis requires a projected metre grid.')
    require(z.size*max_factor<=40_000_000,'Multiscale aggregation work budget exceeded.')
    for f in range(1,max_factor+1):
        hh,ww=h//f,w//f
        if min(hh,ww)<2:break
        blocks=z[:hh*f,:ww*f].reshape(hh,f,ww,f)
        count=np.isfinite(blocks).sum(axis=(1,3));s=np.nansum(blocks,axis=(1,3))
        coarse=np.divide(s,count,out=np.full((hh,ww),np.nan),where=count>0)
        v=coarse[np.isfinite(coarse)]
        if len(v)<3:continue
        rows.append([f,float(grid.transform.a*f),float(abs(grid.transform.e)*f),len(v),
                     float(count.sum()/total),float(v.mean()),float(v.std()),descriptive_moran(coarse)])
    require(len(rows)>=2,'Need at least two usable aggregation scales.')
    return ['factor','width_m','height_m','valid_blocks','source_coverage','mean','population_sd','moran_i'],rows,{'scales':len(rows),'origin':'native upper-left','edge_policy':'drop incomplete edge blocks','interpretation':'Descriptive scale sensitivity; not a hypothesis test or complete MAUP zoning experiment.'}


def difference_uncertainty(stack,common,rho):
    """First-order propagation for the exact linear difference A minus B."""
    a,b,sa,sb=stack[:,common]
    require(np.all(sa>=0) and np.all(sb>=0),'Standard uncertainty rasters must be nonnegative.')
    sd=np.sqrt((sa-sb)**2+2*(1-rho)*sa*sb)
    out=np.full(common.shape,np.nan);out[common]=sd
    delta=a-b
    return out,{'correlation':rho,'valid_cells':len(a),'mean_difference':float(delta.mean()),
                'mean_standard_uncertainty':float(sd.mean()),
                'normal_95_interval_excludes_zero':int(np.count_nonzero(np.abs(delta)>1.95996398454*sd)),
                'interval_assumption':'Gaussian marginal errors with supplied same-cell correlation; no across-cell inference.'}


def empirical_variogram(grid,params):
    valid=np.isfinite(grid.values);coords=coordinates(grid,valid);v=grid.values[valid];n=len(v)
    require(3<=n<=3000,'Exact variogram requires 3–3,000 valid observations.')
    bins=params['bins'];limit=params['distance_m'];counts=np.zeros(bins,np.int64)
    sums=np.zeros(bins);distance_sum=np.zeros(bins)
    for i in range(n-1):
        d=np.hypot(*(coords[i+1:]-coords[i]).T)
        keep=(d>0)&(d<=limit);d=d[keep]
        idx=np.minimum((d/limit*bins).astype(int),bins-1)
        counts+=np.bincount(idx,minlength=bins)
        sums+=np.bincount(idx,weights=.5*(v[i+1:][keep]-v[i])**2,minlength=bins)
        distance_sum+=np.bincount(idx,weights=d,minlength=bins)
    rows=[[i+1,float(i*limit/bins),float((i+1)*limit/bins),int(c),
           float(distance_sum[i]/c),float(sums[i]/c)] for i,c in enumerate(counts) if c]
    require(rows,'No pairs fall inside the maximum lag distance.')
    return ['bin','lower_m','upper_m','pairs','mean_distance_m','semivariance'],rows,{'valid_cells':n,'pair_count':int(counts.sum()),'estimator':'Matheron; unordered pairs; no fitted covariance model'}


def fit_spatial_model(grids,params,kind,view):
    from terrain.studio_data import aligned_grids
    stack,valid=aligned_grids(grids,require_same_unit=False);g=grids[0]
    coords=coordinates(g,valid);y=stack[0,valid];x=stack[1:,valid].T;n,p=x.shape
    require(n>=max(12,4*(p+1)),'Insufficient complete observations for spatial model.')
    scale=x.std(axis=0);require(np.all(scale>0),'Predictor columns must vary.')
    mean=x.mean(axis=0);x=(x-mean)/scale
    design=np.column_stack((np.ones(n),x));center=y.mean();yc=y-center
    require(np.linalg.matrix_rank(design)==p+1,'Predictors are collinear.')
    if kind=='spatial_lag_regression':
        require(n<=20000,'Spatial lag regression requires at most 20,000 complete cells.')
        _,i,j=adjacency(np.where(valid,g.values,np.nan))
        a=np.r_[i,j];b=np.r_[j,i];degree=np.bincount(a,minlength=n)
        require(np.all(degree>0),'Spatial lag model requires no isolated complete-case cells.')
        def lag(v):return np.bincount(a,weights=v[b],minlength=n)/degree
        wx=np.column_stack([lag(x[:,q]) for q in range(p)])
        w2x=np.column_stack([lag(wx[:,q]) for q in range(p)])
        instruments=np.column_stack((design,wx,w2x))
        z=np.column_stack((design,lag(yc)))
        # Project on an orthonormal basis of the instrument span (no dense W).
        u,s,_=np.linalg.svd(instruments,full_matrices=False)
        rank=int(np.count_nonzero(s>s[0]*1e-10));require(rank>p+1,'Excluded instruments have no independent variation.')
        q=u[:,:rank];projected=q.T@z
        require(np.linalg.matrix_rank(projected)==p+2 and np.linalg.cond(projected)<1e9,'Spatial lag instruments are rank deficient or ill-conditioned.')
        coef=np.linalg.lstsq(projected,q.T@yc,rcond=None)[0]
        rho=float(coef[-1]);require(abs(rho)<1,'Fitted spatial lag coefficient is outside the stable |rho| < 1 domain.')
        wy=z[:,-1];base=wy-design@np.linalg.lstsq(design,wy,rcond=None)[0];full=wy-q@(q.T@wy)
        ss0=float(base@base);ss1=float(full@full);require(ss0>0,'Spatial lag has no excluded-instrument variation.')
        partial_r2=float(np.clip(1-ss1/ss0,0,1));df=n-rank;require(df>0,'Insufficient instrument residual degrees of freedom.')
        f=float((ss0-ss1)/(rank-p-1)/(ss1/df)) if ss1>1e-24*ss0 else None
        pred=center+z@coef
        meta={'rho':rho,'intercept':float(coef[0]+(1-rho)*center-(coef[1:-1]/scale)@mean),
              'coefficients':(coef[1:-1]/scale).tolist(),'instrument_rank':rank,
              'first_stage_partial_r_squared':partial_r2,'first_stage_f_diagnostic':f,
              'interpretation':'Structural two-stage least squares with rook-row-standardized Wy; fitted values condition on observed neighboring outcomes, not out-of-sample forecasts. Instrument validity and causal identification are not established.'}
        local=None
    else:
        require(n<=1500 and n*n*(p+1)**2<=80_000_000,'Geographically weighted leave-one-out fit exceeds bounded workspace.')
        pred=np.full(n,np.nan);local=np.full(n,np.nan);effective=np.full(n,np.nan)
        bandwidth=params['bandwidth_m']
        for i,point in enumerate(coords):
            d=np.hypot(*(coords-point).T)/bandwidth
            w=np.exp(-.5*np.minimum(d,40)**2);w[i]=0
            neff=w.sum()**2/max(float(w@w),np.finfo(float).tiny)
            if neff<=p+1:continue
            root=np.sqrt(w);weighted=design*root[:,None]
            if np.linalg.matrix_rank(weighted)<p+1 or np.linalg.cond(weighted)>1e9:continue
            coef=np.linalg.lstsq(weighted,yc*root,rcond=None)[0]
            pred[i]=center+design[i]@coef;local[i]=coef[1]/scale[0];effective[i]=neff
        require(np.count_nonzero(np.isfinite(pred))>=max(3,p+2),'Too few locally identifiable predictions; increase bandwidth.')
        meta={'bandwidth_m':bandwidth,'unpredicted_cells':int(np.count_nonzero(~np.isfinite(pred))),
              'median_effective_neighbors':float(np.nanmedian(effective)),
              'interpretation':'Fixed Gaussian-kernel local regression; focal response omitted for each prediction. Nearby training cells remain, so this is not spatial-block external validation.'}
    good=np.isfinite(pred);residual=y-pred;out=np.full(valid.shape,np.nan)
    out[valid]=pred if view=='prediction' else residual
    resid_grid=np.full(valid.shape,np.nan);resid_grid[valid]=residual
    meta.update(rmse=float(np.sqrt(np.mean(residual[good]**2))),mae=float(np.mean(abs(residual[good]))),
                residual_moran_i=descriptive_moran(resid_grid),evaluated_cells=int(good.sum()),view=view)
    headers=['easting','northing','observed','prediction','residual']
    rows=[[float(a),float(b),float(c),float(d),float(e)] for (a,b),c,d,e in zip(coords[good],y[good],pred[good],residual[good])]
    if local is not None:
        headers.append('local_coefficient_first_predictor')
        for row,c in zip(rows,local[good]):row.append(float(c))
    return out,headers,rows,meta
