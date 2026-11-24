"""Progressive morphology and covariance-weighted rigid alignment."""
import itertools
import numpy as np
from scipy.ndimage import distance_transform_edt, grey_opening
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

def progressive_morphology(p,size,radius,threshold):
    """Progressive morphological filtering on a bounded lower-envelope raster.

    The maximum window radius is explicit; gaps farther than this radius are
    excluded. Nearest-fill is only an internal morphological support model.
    """
    if radius<size or threshold<=0:raise ValueError("Maximum window radius must exceed cell size; threshold must be positive.")
    key=np.floor(p[:,:2]/size).astype(np.int64);key-=key.min(axis=0)
    nx,ny=map(int,key.max(axis=0)+1)
    if nx*ny>1_000_000:raise ValueError("PMF grid exceeds one million cells; increase cell size or clip extent.")
    steps=int(np.floor(radius/size))
    if steps>64:raise ValueError("Maximum morphology radius is 64 cells.")
    z=np.full((ny,nx),np.inf)
    np.minimum.at(z,(key[:,1],key[:,0]),p[:,2])
    valid=np.isfinite(z)
    distance,index=distance_transform_edt(~valid,return_indices=True)
    filled=z[tuple(index)]
    candidate=valid.copy()
    windows=sorted(set([2**i for i in range(7) if 2**i<=steps]+[steps]))
    previous=0;history=[]
    for w in windows:
        opened=grey_opening(filled,size=(2*w+1,2*w+1),mode="nearest")
        # Progressive slope-dependent tolerance capped by the user's maximum.
        delta=min(threshold,.15+.3*(w-previous)*size)
        candidate &= (filled-opened<=delta+1e-10)&(distance<=steps)
        history.append({"radius_m":w*size,"threshold_m":delta,"remaining_cells":int(candidate.sum())})
        # Retain the progressive morphological surface for the next scale.
        filled=opened
        previous=w
    cell_ground=candidate[key[:,1],key[:,0]]
    low=z[key[:,1],key[:,0]]
    seeds=cell_ground&(p[:,2]-low<=1e-8)
    if seeds.sum()<3:raise ValueError("PMF retained insufficient ground support.")
    from .lidar_science import _ground
    ground=_ground(p,p[seeds],radius*2)
    h=p[:,2]-ground
    supported=np.isfinite(h)
    labels=np.where(supported,(np.abs(h)<=threshold).astype(float),np.nan)
    return np.column_stack((p,ground,h,labels)),{"ground_seed_points":int(seeds.sum()),
        "ground_points":int(np.nansum(labels==1)),"nonground_points":int(np.nansum(labels==0)),
        "unsupported_points":int((~supported).sum()),"grid_cells":nx*ny,"window_history":history,
        "initial_tolerance_m":.15,"slope_allowance":.3,"maximum_tolerance_m":threshold}

def coarse_pca_registration(source,reference,radius,trim):
    """Enumerate all 24 proper signed PCA-axis permutations.

    This is a bounded global-orientation initializer for similar extents, not
    a globally optimal or partial-overlap feature registration guarantee.
    """
    if min(len(source),len(reference))<6:raise ValueError("Need at least six points per cloud.")
    a,b=source.mean(axis=0),reference.mean(axis=0)
    s=source-a;q=reference-b
    _,u=np.linalg.eigh(s.T@s/len(s));_,v=np.linalg.eigh(q.T@q/len(q))
    tree=cKDTree(q)
    sample=s[np.linspace(0,len(s)-1,min(10000,len(s)),dtype=int)]
    keep=max(3,int(np.ceil(trim*len(sample))))
    candidates=[]
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((-1.,1.),repeat=3):
            r=v[:,perm]@np.diag(signs)@u.T
            if np.linalg.det(r)<0:continue
            d,_=tree.query(sample@r.T)
            best=np.partition(d,keep-1)[:keep]
            candidates.append((float(np.sqrt(np.mean(best**2))),r))
    candidates.sort(key=lambda x:x[0])
    score,rotation=candidates[0]
    transformed=s@rotation.T+b
    d,_=tree.query(transformed-b)
    inlier=d<=radius
    return np.column_stack((transformed,d,inlier)),{"orientation_candidates":len(candidates),
        "best_trimmed_rmse_m":score,"second_trimmed_rmse_m":candidates[1][0],
        "inlier_fraction":float(inlier.mean()),"rotation_matrix":rotation.tolist(),
        "translation_m":(b-rotation@a).tolist(),"sample_points":len(sample),
        "initialization":"PCA axes and centroid; may be ambiguous for symmetric or incomplete clouds"}

def _covariances(p,k,epsilon):
    if len(p)<k:raise ValueError("Cloud has fewer points than covariance neighbors.")
    tree=cKDTree(p);cov=np.empty((len(p),3,3))
    for i in range(0,len(p),2048):
        j=min(i+2048,len(p));_,idx=tree.query(p[i:j],k=k)
        q=p[idx];q-=q.mean(axis=1,keepdims=True)
        c=np.einsum("nki,nkj->nij",q,q)/k
        eig,vec=np.linalg.eigh(c)
        # Preserve principal variances with a positive absolute noise floor.
        eig=np.maximum(eig,epsilon**2)
        cov[i:j]=(vec*eig[:,None,:])@vec.transpose(0,2,1)
    return cov

def generalized_icp(source,reference,k,radius,trim,iterations,tolerance,epsilon):
    """GICP-style alternating covariance-weighted Gauss–Newton registration.

    Both clouds supply regularized local covariance. The covariance is rotated
    and re-evaluated every iteration but held fixed within each linear solve.
    """
    if epsilon<=0:raise ValueError("Positive covariance noise floor required.")
    origin=reference.mean(axis=0);p=source-origin;ref=reference-origin
    sc=_covariances(p,k,epsilon);rc=_covariances(ref,k,epsilon)
    tree=cKDTree(ref);rotation=np.eye(3);shift=np.zeros(3)
    history=[];converged=False
    for _ in range(iterations):
        d,idx=tree.query(p);use=np.flatnonzero(d<=radius)
        if len(use)<6:raise ValueError("GICP needs at least six correspondences.")
        use=use[np.argsort(d[use],kind="stable")[:max(6,int(np.ceil(trim*len(use))))]]
        q=p[use];res=q-ref[idx[use]]
        cov=rotation@sc[use]@rotation.T+rc[idx[use]]
        l=np.linalg.cholesky(cov)
        length=max(float(np.sqrt(np.mean(np.sum(q*q,axis=1)))),1e-6)
        x,y,z=q.T/length;zero=np.zeros(len(q))
        jac=np.stack((zero,z,-y,-z,zero,x,y,-x,zero),axis=1).reshape(-1,3,3)
        jac=np.concatenate((jac,np.broadcast_to(np.eye(3),(len(q),3,3))),axis=2)
        a=np.linalg.solve(l,jac).reshape(-1,6)
        b=np.linalg.solve(l,-res[:,:,None]).reshape(-1)
        delta,_,rank,s=np.linalg.lstsq(a,b,rcond=1e-10)
        if rank<6:raise ValueError("GICP correspondences do not constrain six rigid dimensions.")
        dr=Rotation.from_rotvec(delta[:3]/length).as_matrix();dt=delta[3:]
        updated=p@dr.T+dt
        step=float(np.sqrt(np.mean(np.sum((updated[use]-p[use])**2,axis=1))))
        p=updated;rotation=dr@rotation;shift=dr@shift+dt
        history.append(float(np.mean(np.sum(b.reshape(-1,3)**2,axis=1))))
        if step<=tolerance:converged=True;break
    d,idx=tree.query(p);inlier=d<=radius
    cov=rotation@sc@rotation.T+rc[idx]
    residual=p-ref[idx]
    mahal=np.sum(np.linalg.solve(np.linalg.cholesky(cov),residual[:,:,None])[:,:,0]**2,axis=1)
    return np.column_stack((p+origin,d,mahal,inlier)),{"converged":converged,"iterations":len(history),
        "rotation_matrix":rotation.tolist(),"translation_m":(origin+shift-rotation@origin).tolist(),
        "inlier_fraction":float(inlier.mean()),"condition_number":float(s[0]/s[-1]),
        "covariance_floor_m":epsilon,"mahalanobis_history":history}
