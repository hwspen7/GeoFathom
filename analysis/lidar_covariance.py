"""Conditional anisotropic measurement covariance and estimated-normal propagation."""
import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import norm
from .lidar_inference import _by_adjust

def covariance_change(current,reference,cores,k,radius,half_depth,sigma_xy,sigma_z,sigma_reg,minimum):
    """Normal-projected displacement with first-order covariance propagation.

    Local sample covariance already contains measurement scatter. The supplied
    independent measurement covariance is a lower bound on mean covariance,
    not an additional copy of the same error. Normal covariance uses the
    Gaussian PCA eigenvector perturbation approximation; shared sample/normal
    dependence is not modeled. Report conditional, not calibrated, intervals.
    """
    if len(reference)<k or len(cores)>10000 or min(sigma_xy,sigma_z,sigma_reg)<0:
        raise ValueError("Invalid covariance-change support.")
    a,b=cKDTree(current),cKDTree(reference)
    reach=float(np.hypot(radius,half_depth))
    candidates=int(a.query_ball_point(cores,reach,return_length=True).sum()+b.query_ball_point(cores,reach,return_length=True).sum())
    if candidates>5_000_000:raise ValueError("Cylinder candidate budget exceeded.")
    _,idx=b.query(cores,k=k)
    out=np.full((len(cores),13),np.nan)
    noise=np.diag([sigma_xy**2,sigma_xy**2,sigma_z**2])
    for i,(center,neighbors) in enumerate(zip(cores,idx)):
        x=reference[neighbors]-center;x-=x.mean(axis=0)
        eig,v=np.linalg.eigh(x.T@x/(k-1));eig=np.maximum(eig,0)
        if eig[2]<=0 or eig[1]-eig[0]<=eig[2]*1e-8:continue
        n=v[:,0];axis=np.flatnonzero(np.abs(n)>1e-12)[-1]
        if n[axis]<0:n=-n
        angular=eig[0]*eig[1:]/((k-1)*(eig[1:]-eig[0])**2)
        cn=(v[:,1:]*angular)@v[:,1:].T
        samples=[]
        for points,tree in ((current,a),(reference,b)):
            d=points[tree.query_ball_point(center,reach)]-center
            axial=d@n;radial=np.maximum(0,np.einsum("ij,ij->i",d,d)-axial**2)
            samples.append(d[(np.abs(axial)<=half_depth)&(radial<=radius**2)])
        x,y=samples
        out[i,:5]=[*n,len(x),len(y)]
        if min(len(x),len(y))<minimum:continue
        delta=x.mean(axis=0)-y.mean(axis=0)
        change=float(n@delta)
        # Use the larger of empirical projection variance or instrumental floor.
        floor=float(n@noise@n)
        var_mean=sum(max(float(np.var(d@n,ddof=1)),floor)/len(d) for d in (x,y))
        var_normal=max(0.,float(delta@cn@delta))
        variance=var_mean+var_normal+sigma_reg**2
        if variance<=0:continue
        se=np.sqrt(variance);lod=norm.ppf(.975)*se
        out[i,5:12]=[change,var_mean,var_normal,se,lod,float(2*norm.sf(abs(change)/se)),np.sqrt(np.trace(cn))]
    out[:,12]=_by_adjust(out[:,10])
    valid=np.isfinite(out[:,12])
    return np.column_stack((cores,out)),{"tested_cores":int(valid.sum()),
        "unsupported_cores":int((~valid).sum()),"fdr_significant_cores":int((out[:,12]<=.05).sum()),
        "horizontal_sigma_m":sigma_xy,"vertical_sigma_m":sigma_z,"registration_sigma_m":sigma_reg,
        "candidate_points":candidates,"assumptions":"independent returns; Gaussian PCA perturbation; fixed correspondence; no cross-covariance; conditional BY FDR"}
