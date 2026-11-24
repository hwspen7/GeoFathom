"""Feature-based alignment, cluster-aware change inference and canopy segmentation."""
import heapq
import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import t
from .lidar_advanced import _rigid_fit

def feature_registration(source, reference, k, radius, ratio, iterations, minimum):
    """Reciprocal invariant kNN-distance descriptors + three-point RANSAC.

    Descriptors are invariant to rigid motion, not changes in sampling density.
    Consensus is based on feature correspondences, and observed bidirectional
    spatial overlap is independently reported after the fit.
    """
    if not 0 < ratio < 1 or min(len(source),len(reference))<max(k+1,minimum,3):
        raise ValueError("Feature registration needs sufficient points and a ratio strictly between zero and one.")
    if max(len(source),len(reference))>30000:
        raise ValueError("Feature alignment limit is 30,000 points per epoch; use voxel reduction first.")
    def descriptors(p):
        d,_=cKDTree(p).query(p,k=k+1)
        return d[:,1:]
    a,b=descriptors(source),descriptors(reference)
    d,ix=cKDTree(b).query(a,k=2)
    _,back=cKDTree(a).query(b)
    keep=(d[:,1]>1e-12)&(d[:,0]<ratio*d[:,1])&(back[ix[:,0]]==np.arange(len(a)))
    src=source[keep];dst=reference[ix[keep,0]]
    if len(src)<max(3,minimum):
        raise ValueError("Insufficient distinctive reciprocal feature matches.")
    rng=np.random.default_rng(42);best=None;best_error=np.inf;trials=0
    # At most 2,000 hypotheses and 60 million match evaluations.
    budget=min(2000,iterations*20,60_000_000//len(src))
    for _ in range(budget):
        trials+=1
        sample=rng.choice(len(src),3,replace=False)
        try:r,shift=_rigid_fit(src[sample],dst[sample])
        except ValueError:continue
        residual=np.linalg.norm(src@r.T+shift-dst,axis=1)
        inlier=residual<=radius
        count=int(inlier.sum())
        if count<minimum:continue
        error=float(np.mean(residual[inlier]**2))
        if best is None or count>best.sum() or (count==best.sum() and error<best_error):
            best=inlier;best_error=error
        if count==len(src):break
    if best is None:raise ValueError("No supported rigid feature consensus.")
    for _ in range(3):
        r,shift=_rigid_fit(src[best],dst[best])
        residual=np.linalg.norm(src@r.T+shift-dst,axis=1)
        updated=residual<=radius
        if updated.sum()<minimum:raise ValueError("Refined feature consensus lost support.")
        if np.array_equal(updated,best):break
        best=updated
    r,shift=_rigid_fit(src[best],dst[best])
    residual=np.linalg.norm(src@r.T+shift-dst,axis=1)
    best=residual<=radius
    if best.sum()<minimum:raise ValueError("Final fit lacks support.")
    transformed=source@r.T+shift
    forward,_=cKDTree(reference).query(transformed)
    reverse,_=cKDTree(transformed).query(reference)
    inside=forward<=radius
    return np.column_stack((transformed,forward,inside)),{
        "feature_matches":len(src),"consensus_matches":int(best.sum()),"ransac_trials":trials,
        "feature_rmse_m":float(np.sqrt(np.mean(residual[best]**2))),
        "source_overlap_fraction":float(inside.mean()),"reference_overlap_fraction":float(np.mean(reverse<=radius)),
        "rotation_matrix":r.tolist(),"translation_m":shift.tolist(),"seed":42,
        "assumption":"locally comparable sampling density; no global optimum guarantee"}

def _cluster_variance(axial, xy, spacing):
    """One-way cluster sandwich variance of a return-weighted mean."""
    keys=np.floor(xy/spacing).astype(np.int64)
    _,inv=np.unique(keys,axis=0,return_inverse=True)
    g=int(inv.max())+1
    if g<3:return np.nan,g
    n=len(axial)
    sums=np.bincount(inv,weights=axial-axial.mean())
    return float(g/(g-1)*np.dot(sums,sums)/n**2),g

def _by_adjust(p):
    """Benjamini-Yekutieli adjustment under arbitrary test dependence."""
    p=np.asarray(p,float)
    out=np.full(p.shape,np.nan)
    valid=np.flatnonzero(np.isfinite(p))
    m=len(valid)
    if not m:return out
    ix=valid[np.argsort(p[valid],kind="stable")]
    harmonic=np.sum(1/np.arange(1,m+1))
    q=p[ix]*m*harmonic/np.arange(1,m+1)
    out[ix]=np.minimum(1,np.minimum.accumulate(q[::-1])[::-1])
    return out

def clustered_normal_change(current,reference,cores,k,radius,half_depth,block,registration_sigma,minimum):
    """Cylinder normal change with tangent-plane clustered uncertainty and BY FDR.

    The block sandwich estimator permits within-block dependence, but assumes
    between-block independence within an epoch. Registration sigma is known
    and independent; normals are treated as fixed. BY controls dependence
    across tests conditional on valid marginal p-values.
    """
    if len(reference)<k or len(cores)>10000 or block<=0 or minimum<3:
        raise ValueError("Invalid clustered change support or block size.")
    a,b=cKDTree(current),cKDTree(reference)
    reach=float(np.hypot(radius,half_depth))
    count=int(a.query_ball_point(cores,reach,return_length=True).sum()+b.query_ball_point(cores,reach,return_length=True).sum())
    if count>5_000_000:raise ValueError("Cylinder candidate budget exceeded; increase core spacing.")
    _,idx=b.query(cores,k=k)
    out=np.full((len(cores),15),np.nan)
    for i,(center,neighbors) in enumerate(zip(cores,idx)):
        local=reference[neighbors];d=local-local.mean(axis=0)
        eig,vec=np.linalg.eigh(d.T@d/k)
        if eig[2]<=0 or eig[1]-eig[0]<=eig[2]*1e-10:continue
        n=vec[:,0];axis=np.flatnonzero(np.abs(n)>1e-12)[-1]
        if n[axis]<0:n=-n
        # Construct a deterministic world-axis tangent frame, avoiding PCA
        # in-plane axis ambiguity on isotropic planar neighborhoods.
        seed=np.eye(3)[np.argmin(np.abs(n))]
        u=np.cross(n,seed);u/=np.linalg.norm(u);v=np.cross(n,u)
        samples=[]
        for points,tree in ((current,a),(reference,b)):
            delta=points[tree.query_ball_point(center,reach)]-center
            h=delta@n;xy=np.column_stack((delta@u,delta@v))
            good=(np.abs(h)<=half_depth)&(np.sum(xy**2,axis=1)<=radius**2)
            samples.append((h[good],xy[good]))
        (x,xx),(y,yy)=samples
        out[i,:5]=[*n,len(x),len(y)]
        if min(len(x),len(y))<minimum:continue
        vx,gx=_cluster_variance(x,xx,block);vy,gy=_cluster_variance(y,yy,block)
        out[i,5:7]=[gx,gy]
        if not np.isfinite(vx+vy):continue
        change=float(x.mean()-y.mean())
        se=float(np.sqrt(vx+vy+registration_sigma**2))
        df=min(gx,gy)-1
        lod=float(t.ppf(.975,df)*se)
        # Zero variance is a degenerate model, not proof of infinite precision.
        if se<=0:continue
        p=float(2*t.sf(abs(change)/se,df))
        out[i,7:13]=[change,se,lod,change-lod,change+lod,p]
    q=_by_adjust(out[:,12]);out[:,13]=q;out[:,14]=np.where(np.isfinite(q),q<=.05,np.nan)
    valid=np.isfinite(q)
    return np.column_stack((cores,out)),{
        "tested_cores":int(valid.sum()),"unsupported_cores":int((~valid).sum()),
        "fdr_significant_cores":int(np.nansum(out[:,14])),"fdr_level":.05,
        "tangent_block_m":block,"registration_sigma_m":registration_sigma,
        "candidate_points":count,"minimum_blocks_per_epoch":3,
        "inference":"cluster sandwich variance, conservative t degrees of freedom and BY-adjusted p values; fixed normals and independent blocks assumed"}

def canopy_watershed(p,ground,size,radius,threshold):
    """Sparse CHM marker-controlled maximum-bottleneck watershed.

    Only occupied above-threshold cells participate. The eight-neighbor graph
    cannot cross an unobserved gap. Peaks use metric nonmaximum suppression;
    ties are broken deterministically. Cell footprint is observed support.
    """
    h=p[:,2]-ground
    good=np.isfinite(h)&(h>=threshold)
    if not good.any():raise ValueError("No supported canopy returns above threshold.")
    keys,inv=np.unique(np.floor(p[good,:2]/size).astype(np.int64),axis=0,return_inverse=True)
    top=np.full(len(keys),-np.inf);np.maximum.at(top,inv,h[good])
    xy=(keys+.5)*size;tree=cKDTree(xy)
    order=np.lexsort((keys[:,1],keys[:,0],-top))
    suppressed=np.zeros(len(keys),bool);seeds=[]
    for i in order:
        if suppressed[i]:continue
        seeds.append(int(i))
        suppressed[tree.query_ball_point(xy[i],radius)]=True
    lookup={tuple(key):i for i,key in enumerate(keys)}
    labels=np.full(len(keys),-1,int);score=np.full(len(keys),-np.inf)
    queue=[];fixed=set(seeds)
    for label,i in enumerate(seeds):
        labels[i]=label;score[i]=top[i];heapq.heappush(queue,(-top[i],label,i))
    while queue:
        neg,label,i=heapq.heappop(queue)
        s=-neg
        if labels[i]!=label or score[i]!=s:continue
        x,y=keys[i]
        for dx,dy in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
            j=lookup.get((x+dx,y+dy))
            if j is None or j in fixed:continue
            new=min(s,top[j])
            if new>score[j] or (new==score[j] and label<labels[j]):
                score[j]=new;labels[j]=label;heapq.heappush(queue,(-new,label,j))
    # Suppression may remove all markers on a disconnected island; leave it unknown.
    counts=np.bincount(inv,minlength=len(keys))
    table=np.column_stack((xy,top,labels,counts,np.where(labels>=0,score,np.nan)))
    summary=[]
    for label,i in enumerate(seeds):
        mask=labels==label
        summary.append({"id":label,"apex_xy_m":xy[i].tolist(),"apex_height_m":float(top[i]),
            "occupied_footprint_m2":float(mask.sum()*size**2),"returns":int(counts[mask].sum())})
    return table,{"candidate_crowns":len(seeds),"assigned_cells":int((labels>=0).sum()),
        "unassigned_cells":int((labels<0).sum()),"unsupported_ground_returns":int((~np.isfinite(h)).sum()),
        "crowns":summary[:100],"reported_crown_summaries":min(100,len(summary)),
        "assumption":"occupied CHM footprint only; candidate instances, not validated biological crowns"}

def multiscale_geometry(p,k):
    """Select local covariance scale by minimum normalized eigenentropy.

    Candidate supports are k/2, k and 2k (bounded by 128); ambiguous normals
    are excluded before selection. Entropy is a geometric heuristic.
    """
    sizes=sorted(set([max(3,k//2),k,min(128,k*2)]))
    sizes=[s for s in sizes if s<=len(p)]
    if not sizes:raise ValueError("Insufficient neighborhood points.")
    tree=cKDTree(p);result=np.full((len(p),8),np.nan)
    for start in range(0,len(p),1024):
        end=min(start+1024,len(p));d,idx=tree.query(p[start:end],k=max(sizes))
        best=np.full(end-start,np.inf);out=result[start:end]
        for s in sizes:
            q=p[idx[:,:s]];q-=q.mean(axis=1,keepdims=True)
            eig,vec=np.linalg.eigh(np.einsum("nki,nkj->nij",q,q)/s)
            eig=np.maximum(eig,0);total=eig.sum(axis=1)
            prob=np.divide(eig,total[:,None],out=np.zeros_like(eig),where=total[:,None]>0)
            entropy=-np.sum(prob*np.log(np.maximum(prob,1e-300)),axis=1)/np.log(3)
            valid=(eig[:,2]>0)&(eig[:,1]-eig[:,0]>eig[:,2]*1e-10)&(entropy<best)
            n=vec[:,:,0];sign=np.where(np.abs(n[:,2])>1e-12,n[:,2],np.where(np.abs(n[:,1])>1e-12,n[:,1],n[:,0]))
            n=n*np.where(sign<0,-1,1)[:,None]
            a,b,c=eig[valid].T
            out[valid]=np.column_stack((np.full(valid.sum(),s),d[valid,s-1],entropy[valid],n[valid],np.sqrt(a),(b-a)/c))
            best[valid]=entropy[valid]
    valid=np.isfinite(result[:,0])
    return np.column_stack((p,result)),{"candidate_neighbors":sizes,"valid_points":int(valid.sum()),
        "selected_counts":{str(s):int(np.sum(result[:,0]==s)) for s in sizes},
        "selection":"minimum normalized eigenentropy over identifiable local covariance normals"}
