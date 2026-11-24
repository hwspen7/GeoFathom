"""Registration and conditional change inference for bounded metric point clouds."""
import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import t

def robust_outlier(points,k,threshold):
    """Robust statistical outlier score from mean k-nearest-neighbor distance."""
    if len(points)<=k:
        raise ValueError("Need more points than requested neighbors.")
    tree=cKDTree(points)
    means=np.empty(len(points))
    for start in range(0,len(points),4096):
        stop=min(start+4096,len(points))
        d,_=tree.query(points[start:stop],k=k+1)
        means[start:stop]=d[:,1:].mean(axis=1)
    med=float(np.median(means))
    sigma=1.4826*float(np.median(np.abs(means-med)))
    # An exactly regular cloud has zero MAD. Use a scale-aware numerical tolerance,
    # not division by zero or a fabricated statistical significance.
    tol=max(np.finfo(float).eps*max(1.,abs(med))*32,1e-12)
    if sigma<=tol:
        score=np.full(len(points),np.nan)
        outlier=means>med+tol
    else:
        score=(means-med)/sigma
        outlier=score>threshold
    return np.column_stack((means,score,outlier)),{"median_knn_m":med,"mad_scale_m":sigma,
        "threshold":threshold,"flagged_points":int(outlier.sum()),"zero_mad":bool(sigma<=tol)}

def _rigid_fit(source,target):
    a,b=source.mean(axis=0),target.mean(axis=0)
    h=(source-a).T@(target-b)
    u,s,vt=np.linalg.svd(h)
    if s[0]<=0 or s[1]<=s[0]*1e-12:
        raise ValueError("Registration correspondences are degenerate.")
    r=vt.T@u.T
    if np.linalg.det(r)<0:
        vt[-1]*=-1
        r=vt.T@u.T
    return r,b-r@a

def register(source,reference,max_distance,trim_fraction,max_iterations,tolerance):
    """Trimmed point-to-point ICP. Reference is fixed; source is transformed."""
    if min(len(source),len(reference))<3:
        raise ValueError("Registration requires at least three points in each cloud.")
    if not .5<=trim_fraction<=1 or not 1<=max_iterations<=100 or not 1e-9<=tolerance<=1.:
        raise ValueError("Invalid ICP parameters.")
    tree=cKDTree(reference)
    # Work in a common centered frame to avoid translation-dependent precision loss.
    origin=reference.mean(axis=0)
    tree=cKDTree(reference-origin)
    p=source-origin
    rot=np.eye(3)
    shift=np.zeros(3)
    history=[]
    converged=False
    for _ in range(max_iterations):
        d,idx=tree.query(p)
        valid=np.flatnonzero(d<=max_distance)
        keep=max(3,int(np.ceil(len(valid)*trim_fraction)))
        if len(valid)<3:
            raise ValueError("Insufficient correspondences within registration distance.")
        use=valid[np.argsort(d[valid],kind="stable")[:keep]]
        target=(reference-origin)[idx[use]]
        r,tv=_rigid_fit(p[use],target)
        updated=p@r.T+tv
        step=float(np.sqrt(np.mean(np.sum((updated[use]-p[use])**2,axis=1))))
        p=updated
        rot=r@rot
        shift=r@shift+tv
        history.append(float(np.sqrt(np.mean(np.sum((p[use]-target)**2,axis=1)))))
        if step<=tolerance:
            converged=True
            break
    d,_=tree.query(p)
    inlier=d<=max_distance
    transformed=p+origin
    translation=origin+shift-rot@origin
    return np.column_stack((transformed,d,inlier)),{"converged":converged,"iterations":len(history),
        "inlier_points":int(inlier.sum()),"inlier_fraction":float(inlier.mean()),
        "inlier_rmse_m":float(np.sqrt(np.mean(d[inlier]**2))) if inlier.any() else None,
        "rotation_matrix":rot.tolist(),"translation_m":translation.tolist(),"trimmed_rmse_history_m":history,
        "initialization":"identity; requires approximate prior alignment"}

def normal_change(current,reference,cores,k,radius,half_depth,registration_sigma,min_neighbors):
    """M3C2-inspired local projection; conditional pointwise Welch intervals.

    The baseline local PCA normal is estimated from k neighbors. Both epochs
    are sampled in a cylinder centered on the same baseline core coordinate.
    Confidence intervals assume independent point samples, independent known
    registration uncertainty, and fixed normals. Spatial correlation and
    normal-estimation error are not included.
    """
    if len(reference)<k or min_neighbors<3 or registration_sigma<0:
        raise ValueError("Invalid reference neighborhood or registration uncertainty.")
    if len(cores)>10000:
        raise ValueError("Too many core points; increase the core voxel size.")
    a,b=cKDTree(current),cKDTree(reference)
    reach=float(np.hypot(radius,half_depth))
    # Bound the candidate work before allocating neighbor lists.
    candidate=int(a.query_ball_point(cores,reach,return_length=True).sum()+b.query_ball_point(cores,reach,return_length=True).sum())
    if candidate>5_000_000:
        raise ValueError("Cylinder candidate budget exceeded; reduce radius/depth or increase core spacing.")
    _,idx=b.query(cores,k=k)
    out=np.full((len(cores),10),np.nan)
    for i,(center,neighbors) in enumerate(zip(cores,idx)):
        local=reference[neighbors]
        d=local-local.mean(axis=0)
        eig,vec=np.linalg.eigh(d.T@d/k)
        if eig[2]<=0 or eig[1]-eig[0]<=eig[2]*1e-10:
            continue
        n=vec[:,0]
        dominant=n[2] if abs(n[2])>1e-12 else n[1] if abs(n[1])>1e-12 else n[0]
        if dominant<0:n=-n
        values=[]
        for points,tree in ((current,a),(reference,b)):
            delta=points[tree.query_ball_point(center,reach)]-center
            axial=delta@n
            radial=np.maximum(0,np.einsum("ij,ij->i",delta,delta)-axial**2)
            values.append(axial[(np.abs(axial)<=half_depth)&(radial<=radius**2)])
        x,y=values
        out[i,:5]=[*n,len(x),len(y)]
        if min(len(x),len(y))<min_neighbors:
            continue
        change=float(x.mean()-y.mean())
        vx=float(x.var(ddof=1)/len(x));vy=float(y.var(ddof=1)/len(y))
        variance=vx+vy+registration_sigma**2
        denom=vx**2/(len(x)-1)+vy**2/(len(y)-1)
        df=variance**2/denom if denom>0 else np.inf
        lod=float(t.ppf(.975,df)*np.sqrt(variance))
        out[i,5:]=[change,lod,change-lod,change+lod,float(abs(change)>lod)]
    valid=np.isfinite(out[:,5])
    return np.column_stack((cores,out)),{"core_points":len(cores),"valid_cores":int(valid.sum()),
        "unsupported_cores":int((~valid).sum()),"above_detection_limit":int(np.nansum(out[:,9])),
        "registration_sigma_m":registration_sigma,"confidence_level":.95,"candidate_points":candidate,
        "inference":"conditional pointwise interval; not corrected for spatial dependence or multiple comparisons"}

def canopy_structure(points,ground,size,threshold):
    """Per-cell distribution of ground-normalized returns, not area cover or LAI."""
    height=points[:,2]-ground
    valid=np.isfinite(height)
    if not valid.any():
        raise ValueError("No supported ground-normalized returns.")
    h=height[valid]
    keys,inverse,counts=np.unique(np.floor(points[valid,:2]/size).astype(np.int64),axis=0,return_inverse=True,return_counts=True)
    order=np.argsort(inverse,kind="stable")
    groups=np.split(h[order],np.cumsum(counts)[:-1])
    rows=[]
    for key,g in zip(keys,groups):
        q=np.quantile(g,[.05,.25,.5,.75,.95])
        rows.append([*(key+.5)*size,len(g),*q,float(g.mean()),float(g.std()),float(np.mean(g>threshold))])
    return np.asarray(rows),{"supported_returns":int(valid.sum()),"unsupported_returns":int((~valid).sum()),
        "negative_height_returns":int((h<0).sum()),"occupied_cells":len(rows),"height_threshold_m":threshold,
        "return_fraction_above_threshold":float(np.mean(h>threshold))}
