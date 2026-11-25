"""Physical retrieval, covariance inference and spatial validation."""
import numpy as np
from analysis.science_raster import require
from .remote_partitions import spatial_partitions

def surface_temperature(v,p):
    l,e,t,u,d=(v[k] for k in ('radiance','emissivity','transmittance','upwelling','downwelling'))
    b=(l-u-t*(1-e)*d)/(t*e)
    out=np.full(b.shape,np.nan);good=np.isfinite(b)&(b>0)
    out[good]=p['k2']/np.log1p(p['k1']/b[good])
    return out,{'nonpositive_retrieved_radiance_cells':int(np.count_nonzero(np.isfinite(b)&(b<=0))),
                'model':'Single-channel radiative transfer; atmospheric inputs externally supplied.'}

def c_correction(v,p):
    r=v['reflectance'];s=np.deg2rad(v['slope']);a=np.deg2rad(v['aspect'])
    zen=np.deg2rad(p['solar_zenith']);az=np.deg2rad(p['solar_azimuth'])
    illumination=np.cos(s)*np.cos(zen)+np.sin(s)*np.sin(zen)*np.cos(a-az)
    valid=np.isfinite(r)&np.isfinite(illumination)&(illumination>=p['min_cosine'])
    train=valid&(v['calibration']==1)
    require(train.sum()>=10,'C-correction requires ten illuminated calibration cells.')
    x=illumination[train];y=r[train];xc=x-x.mean()
    require(xc@xc>1e-10,'Calibration illumination must vary.')
    m=float(xc@(y-y.mean())/(xc@xc));b=float(y.mean()-m*x.mean())
    require(m>1e-10 and b>=0,'Positive slope and nonnegative intercept required for C correction.')
    c=b/m;out=np.full(r.shape,np.nan);out[valid]=r[valid]*(np.cos(zen)+c)/(illumination[valid]+c)
    return out,{'c':c,'slope':m,'intercept':b,'calibration_cells':int(train.sum()),
                'excluded_cells':int((~valid).sum()),'solar_geometry':'aspect and azimuth clockwise from grid north'}

def ndvi_uncertainty(v,p):
    n,r,sn,sr=(v[k] for k in ('nir','red','nir_sd','red_sd'))
    good=np.isfinite(n)&np.isfinite(r)&np.isfinite(sn)&np.isfinite(sr)&(abs(n+r)>p['min_sum'])
    out=np.full(n.shape,np.nan);den=(n[good]+r[good])**2
    a=2*r[good]/den*sn[good];b=-2*n[good]/den*sr[good]
    out[good]=np.sqrt(np.maximum(0,a*a+b*b+2*p['correlation']*a*b))
    return out,{'correlation':p['correlation'],'model':'First-order delta method; conditional supplied marginal SDs and correlation.'}

def change_vectors(v,standardize):
    a=np.stack([v[k+'_before'] for k in ('red','nir','swir')])
    b=np.stack([v[k+'_after'] for k in ('red','nir','swir')])
    valid=np.isfinite(a).all(axis=0)&np.isfinite(b).all(axis=0)
    d=(b-a)[:,valid].T;require(len(d)>=4,'At least four paired complete cells required.')
    if standardize:
        stable=v['calibration'][valid]==1
        require(stable.sum()>=10,'At least ten stable reference cells required.')
        ref=d[stable];mu=ref.mean(axis=0);cov=np.cov(ref,rowvar=False)
        scale=float(np.trace(cov)/3);require(scale>0,'Stable change covariance must vary.')
        cov=.98*cov+.02*scale*np.eye(3)
        z=np.linalg.solve(np.linalg.cholesky(cov),(d-mu).T).T
        distance=np.linalg.norm(z,axis=1)
        meta={'stable_cells':int(stable.sum()),'reference_mean_change':mu.tolist(),'reference_covariance':cov.tolist(),
              'shrinkage':.02,'interpretation':'Descriptive Mahalanobis distance; no calibrated change probability.'}
    else:distance=np.linalg.norm(d,axis=1);meta={'interpretation':'Euclidean reflectance change magnitude.'}
    out=np.full(valid.shape,np.nan);out[valid]=distance
    return out,meta

def spatial_classifier(v,grid,p):
    """Regularized LDA with spatially disjoint training and validation blocks."""
    stack=np.stack([v[k] for k in ('blue','green','red','nir')])
    labels=v['training'];valid=np.isfinite(stack).all(axis=0);labeled=valid&np.isfinite(labels)&(labels>0)
    require(grid.is_meter,'Spatial validation requires a projected metre grid.')
    require(p['heldout_fold']<p['folds'],'Held-out fold must be below fold count.')
    fold,excluded=spatial_partitions(valid.shape,grid.transform,p['block_m'],p['folds'],p['buffer_blocks'])
    hold=labeled&(fold==p['heldout_fold']);train=labeled&~excluded[p['heldout_fold']]
    classes=np.unique(labels[labeled]);require(2<=len(classes)<=32,'Use 2–32 labeled classes.')
    x=stack[:,train].T;y=labels[train];means=[];scatter=np.zeros((4,4))
    for c in classes:
        xx=x[y==c];require(len(xx)>=5 and np.count_nonzero(hold&(labels==c))>=2,'Every class needs five training and two held-out cells.')
        mu=xx.mean(axis=0);means.append(mu);scatter+=(xx-mu).T@(xx-mu)
    cov=scatter/(len(x)-len(classes));scale=float(np.trace(cov)/4)
    require(scale>0,'Training spectral covariance has no variation.')
    cov=(1-p['shrinkage'])*cov+p['shrinkage']*scale*np.eye(4)
    means=np.array(means);whiten=np.linalg.cholesky(cov);w=np.linalg.solve(whiten,means.T).T
    require(int(valid.sum())*len(classes)*4<=80_000_000,'Classification work budget exceeded.')
    pred=np.full(valid.shape,np.nan);xx=stack[:,valid].T;out=np.empty(len(xx))
    for i in range(0,len(xx),8192):
        z=np.linalg.solve(whiten,xx[i:i+8192].T).T
        out[i:i+len(z)]=classes[np.argmin(np.sum((z[:,None,:]-w[None,:,:])**2,axis=2),axis=1)]
    pred[valid]=out
    from .remote_kernels import agreement
    headers,rows,metrics=agreement(pred[hold],labels[hold])
    metrics.update(training_cells=int(train.sum()),heldout_cells=int(hold.sum()),excluded_labeled_cells=int((labeled&~train&~hold).sum()),
                   block_m=p['block_m'],heldout_fold=p['heldout_fold'],folds=p['folds'],buffer_blocks=p['buffer_blocks'],
                   partition='recursive_spatial_blocks',class_prior='equal',covariance_condition=float(np.linalg.cond(cov)),
                   interpretation='Held-out spatial block agreement; not independent external-site accuracy. Output uses training-only model.')
    return pred,headers,rows,metrics

def long_series(kind,stack,times,period):
    n,h,w=stack.shape;t=np.asarray(times,float)
    require(len(t)==n and 6<=n<=64 and np.isfinite(t).all() and np.all(np.diff(t)>0),'Supply 6–64 strictly increasing finite acquisition times.')
    require(t[-1]-t[0]<=1e9,'Acquisition time span exceeds supported range.')
    t=t-t[0];valid=np.isfinite(stack);count=valid.sum(axis=0);out=np.full((h,w),np.nan)
    if kind=='series_median':
        good=count>=2;out[good]=np.nanmedian(stack[:,good],axis=0)
    elif kind=='series_count':out=count.astype(float)
    elif kind=='series_slope':
        good=count>=3;tt=t[:,None,None]
        mt=np.divide(np.sum(valid*tt,axis=0),count,out=np.zeros((h,w)),where=count>0)
        my=np.divide(np.nansum(stack,axis=0),count,out=np.zeros((h,w)),where=count>0)
        dx=tt-mt;den=np.sum(np.where(valid,dx*dx,0),axis=0)
        out=np.divide(np.sum(dx*np.where(valid,stack-my,0),axis=0),den,out=out,where=good&(den>0))
    else:
        require(period>0 and t[-1]>=period,'Harmonic model needs at least one full supplied period.')
        require(n*h*w<=2_000_000,'Harmonic design work budget exceeded; crop explicitly.')
        phase=2*np.pi*t/period;design=np.column_stack((np.ones(n),t/t[-1],np.cos(phase),np.sin(phase)))
        flat=stack.reshape(n,-1);packed=np.packbits(np.isfinite(flat).T,axis=1)
        patterns,indices=np.unique(packed,axis=0,return_inverse=True)
        require(len(patterns)<=4096,'Too many distinct missingness patterns for bounded harmonic fit.')
        dest=out.ravel()
        for j,pattern in enumerate(patterns):
            mask=np.unpackbits(pattern)[:n].astype(bool);x=design[mask]
            if mask.sum()<6 or np.linalg.matrix_rank(x)<4 or np.linalg.cond(x)>1e8:continue
            ids=np.flatnonzero(indices==j);coef=np.linalg.lstsq(x,flat[np.ix_(mask,ids)],rcond=None)[0]
            if kind=='series_amplitude':dest[ids]=np.hypot(coef[2],coef[3])
            else:dest[ids]=np.sqrt(np.mean((flat[np.ix_(mask,ids)]-x@coef)**2,axis=0))
    return out,{'acquisitions':n,'times':times,'minimum_observations':0 if kind=='series_count' else 2 if kind=='series_median' else 3 if kind=='series_slope' else 6,
                'model':'Harmonic intercept, linear trend, sine and cosine with fixed period' if kind in {'series_amplitude','series_harmonic_rmse'} else kind,
                'period':period if kind in {'series_amplitude','series_harmonic_rmse'} else None}


def gamma_map(z,r,enl):
    from analysis.science_raster import focal
    mean=focal(z,r,'focal_mean');var=focal(z,r,'focal_sd')**2
    out=z.copy();valid=np.isfinite(z)&(mean>0)
    cv2=np.divide(var,mean**2,out=np.zeros(z.shape),where=valid)
    cu2=1/enl;flat=valid&(cv2<=cu2);mid=valid&(cv2>cu2)&(cv2<2*cu2)
    out[flat]=mean[flat]
    alpha=(1+cu2)/(cv2[mid]-cu2);b=alpha-enl-1;mu=mean[mid];x=z[mid]
    # Normalize the quadratic by alpha to avoid cancellation near the lower threshold.
    q=b/alpha;d=enl/alpha
    out[mid]=(q*mu+np.sqrt((q*mu)**2+4*d*mu*x))/2
    return out,{'homogeneous_cells':int(flat.sum()),'adaptive_cells':int(mid.sum()),'edge_cells':int((valid&~flat&~mid).sum()),'enl':enl}

def mad_distance(v):
    a=np.stack([v[k+'_before'] for k in ('red','nir','swir')])
    b=np.stack([v[k+'_after'] for k in ('red','nir','swir')])
    valid=np.isfinite(a).all(axis=0)&np.isfinite(b).all(axis=0)
    x=a[:,valid].T;y=b[:,valid].T;stable=v['calibration'][valid]==1
    require(stable.sum()>=12,'MAD requires at least twelve stable complete observations.')
    mx=x[stable].mean(axis=0);my=y[stable].mean(axis=0);xc=x[stable]-mx;yc=y[stable]-my
    def whiten(z):
        c=z.T@z/(len(z)-1);eig,vec=np.linalg.eigh(c)
        require(eig[0]>eig[-1]*1e-9 and eig[-1]>0,'Stable spectral covariance is rank deficient.')
        return (vec/np.sqrt(eig))@vec.T
    wx=whiten(xc);wy=whiten(yc);cross=(xc@wx).T@(yc@wy)/(len(xc)-1)
    u,rho,vt=np.linalg.svd(cross,full_matrices=False)
    require(np.all(rho<1-1e-9),'MAD is undefined for perfectly correlated canonical components.')
    left=wx@u;right=wy@vt.T
    delta=(x-mx)@left-(y-my)@right
    variance=2*(1-rho);out=np.full(valid.shape,np.nan)
    out[valid]=np.sum(delta**2/variance,axis=1)
    return out,{'canonical_correlations':rho.tolist(),'stable_cells':int(stable.sum()),'degrees_of_freedom':3,
                'interpretation':'Sum of squared standardized canonical alteration components; calibration-mask conditional descriptive statistic.'}
