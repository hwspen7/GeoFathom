"""Conditional multi-sensor fusion and effective vegetation structure models."""
import numpy as np
from analysis.science_raster import require

def fusion(v,p,kind):
    a,b,sa,sb=(v[k] for k in ('first','second','first_sd','second_sd'))
    rho=p['correlation'];cov=rho*sa*sb
    valid=np.logical_and.reduce([np.isfinite(x) for x in v.values()])&(sa>0)&(sb>0)
    out=np.full(a.shape,np.nan)
    # Scale the covariance algebra to avoid overflow and catastrophic cancellation.
    scale=np.maximum(sa[valid],sb[valid]);x=sa[valid]/scale;y=sb[valid]/scale
    den=(x-y)**2+2*(1-rho)*x*y
    require(np.all(den>1e-12),'Fusion covariance is too ill-conditioned.')
    wa=(y*y-rho*x*y)/den;wb=1-wa
    if kind=='fusion_gls':out[valid]=wa*a[valid]+wb*b[valid]
    elif kind=='fusion_gls_sd':out[valid]=scale*x*y*np.sqrt((1-rho*rho)/den)
    else:out[valid]=((b[valid]-a[valid])/scale)/np.sqrt(den)
    return out,{'paired_cells':int(valid.sum()),'correlation':rho,
                'negative_weight_cells':int(np.count_nonzero((wa<0)|(wb<0))),
                'model':'Two unbiased same-quantity measurements with supplied covariance; GLS minimum-variance linear estimator. Negative weights may occur. No independent calibration implied.'}

def canopy(v,p,kind):
    gap=v['gap'];valid=np.isfinite(gap)&(gap>0)&(gap<=1)
    out=np.full(gap.shape,np.nan)
    # Beer-Lambert directional gap model; the extinction coefficient and
    # clumping are supplied independently, not inferred from NDVI.
    factor=p['extinction']*p['clumping']
    lai=-np.log(gap[valid])/factor
    if kind=='canopy_lai':out[valid]=lai
    else:out[valid]=-np.expm1(-p['par_extinction']*p['clumping']*lai)
    return out,{'zero_gap_cells':int(np.count_nonzero(gap==0)),
                'model':'Conditional Beer-Lambert gap inversion; directional gap, extinction and clumping must be independently supplied. FPAR is an absorption proxy neglecting scattering and background absorption.'}

def unsupervised(v,p,kind):
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    import sklearn
    a=np.stack([v[k] for k in ('blue','green','red','nir')]);valid=np.isfinite(a).all(axis=0)
    x=a[:,valid].T;n=len(x);k=p['clusters']
    require(k*10<=n<=100000 and n*k*p['iterations']<=100_000_000,'Clustering population/work budget exceeded.')
    require(len(np.unique(x,axis=0))>=k,'Insufficient distinct spectra.')
    # Fit standardization and centroids on the same declared unlabeled population.
    scaler=StandardScaler();z=scaler.fit_transform(x)
    model=KMeans(n_clusters=k,n_init=5,max_iter=p['iterations'],random_state=p['seed'],algorithm='lloyd').fit(z)
    centers=scaler.inverse_transform(model.cluster_centers_)
    # Stable class IDs: lexicographic spectral centers, not estimator label order.
    order=np.lexsort(tuple(centers[:,i] for i in range(3,-1,-1)))
    inverse=np.empty(k,int);inverse[order]=np.arange(1,k+1)
    labels=inverse[model.labels_];dist=np.linalg.norm(z-model.cluster_centers_[model.labels_],axis=1)
    out=np.full(valid.shape,np.nan);out[valid]=labels if kind=='spectral_kmeans' else dist
    rows=[[i+1,int(np.count_nonzero(labels==i+1)),*centers[j].tolist()] for i,j in enumerate(order)]
    return out,['cluster','cells','blue','green','red','nir'],rows,{'inertia':float(model.inertia_),'iterations':int(model.n_iter_),
        'sklearn_version':sklearn.__version__,'scaling_mean':scaler.mean_.tolist(),'scaling_sd':scaler.scale_.tolist(),
        'interpretation':'Unsupervised spectral clusters; no land-cover class semantics or independent accuracy. Distance is standardized feature-space distance.'}
