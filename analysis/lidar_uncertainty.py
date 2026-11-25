"""Spatially correlated change uncertainty for common-support cell means."""
import numpy as np
from scipy.spatial import cKDTree

def correlated_change(current,reference,size,registration_sigma,radius,min_neighbors):
    """Cell mean changes with block covariance from a specified exponential model.

    Independent within-cell sampling variances are combined with a spatially
    correlated registration error. Correlation length is supplied, not fitted.
    The normal approximation is conditional on this error model.
    """
    def cells(p):
        keys,inv,n=np.unique(np.floor(p[:,:2]/size).astype(np.int64),axis=0,return_inverse=True,return_counts=True)
        order=np.argsort(inv,kind="stable")
        values=np.split(p[order,2],np.cumsum(n)[:-1])
        return {tuple(k):(float(z.mean()),float(z.var(ddof=1)/len(z)),len(z))
                for k,z in zip(keys,values) if len(z)>=min_neighbors}
    a,b=cells(current),cells(reference);keys=sorted(a.keys()&b.keys())
    if not keys:raise ValueError("No shared cells have the required sample support.")
    if len(keys)>10000:raise ValueError("Covariance calculation limited to 10,000 shared cells.")
    xy=(np.asarray(keys,dtype=float)+.5)*size
    change=np.array([a[k][0]-b[k][0] for k in keys])
    sampling=np.array([a[k][1]+b[k][1] for k in keys])
    n=len(keys)
    # Exact all-pairs exponential covariance in blocks; avoid allocating n^2.
    total=0.
    for i in range(0,n,256):
        d=np.linalg.norm(xy[i:i+256,None,:]-xy[None,:,:],axis=2)
        total+=float(np.exp(-d/radius).sum())
    sigma2=registration_sigma**2
    volume_se=float(size**2*np.sqrt(sampling.sum()+sigma2*total))
    volume=float(change.sum()*size**2)
    se=np.sqrt(sampling+sigma2);lod=1.959963984540054*se
    rows=np.column_stack((xy,[b[k][0] for k in keys],[a[k][0] for k in keys],change,se,lod,
        change-lod,change+lod,np.abs(change)>lod,[a[k][2] for k in keys],[b[k][2] for k in keys]))
    return rows,{"shared_cells":n,"current_only_supported_cells":len(a)-n,"reference_only_supported_cells":len(b)-n,
        "common_area_m2":n*size**2,"net_volume_m3":volume,"volume_standard_uncertainty_m3":volume_se,
        "volume_ci95_m3":[volume-1.959963984540054*volume_se,volume+1.959963984540054*volume_se],
        "registration_sigma_m":registration_sigma,"correlation_length_m":radius,
        "covariance_model":"operator-specified exponential spatial correlation of additive registration error",
        "assumptions":"independent within-cell sample means; conditional Gaussian approximation; no multiple-test adjustment"}
