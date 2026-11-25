"""Ground filtering, bounded reconstruction and structural segmentation.

All distances use the operator-confirmed projected metre coordinate system.
No unsupported terrain cells are interpolated by the classification method.
"""
import numpy as np
from scipy.spatial import cKDTree, Delaunay, QhullError
from scipy.spatial.transform import Rotation

def ground_filter(p,size,radius,threshold):
    """Select low-cell candidates with a local slope allowance.

    A lower-envelope seed is formed per coarse cell. Candidate elevations are
    compared to neighboring accepted seeds, with a maximum slope expressed
    as rise/run. This is a single-pass local slope filter, not progressive TIN, CSF or PMF.
    """
    if threshold<=0 or radius<size:
        raise ValueError("Ground tolerance must be positive and search radius at least one cell.")
    keys,inv=np.unique(np.floor(p[:,:2]/size).astype(np.int64),axis=0,return_inverse=True)
    order=np.lexsort((p[:,2],inv))
    first=np.r_[True,inv[order][1:]!=inv[order][:-1]]
    seeds=order[first]
    xy=p[seeds,:2]
    tree=cKDTree(xy)
    # Reject an isolated elevated cell when nearby lower evidence exists.
    dz=np.full(len(seeds),np.nan)
    support=np.zeros(len(seeds),int)
    for start in range(0,len(seeds),2048):
        stop=min(start+2048,len(seeds))
        d,ix=tree.query(xy[start:stop],k=min(16,len(seeds)),distance_upper_bound=radius)
        d=d.reshape(stop-start,-1);ix=ix.reshape(stop-start,-1)
        good=np.isfinite(d)&(ix!=np.arange(start,stop)[:,None])
        other=p[seeds[np.minimum(ix,len(seeds)-1)],2]
        bound=np.where(good,other+.35*d,np.inf)
        support[start:stop]=good.sum(axis=1)
        dz[start:stop]=np.where(good.any(axis=1),p[seeds[start:stop],2]-bound.min(axis=1),np.nan)
    accepted=seeds[np.isfinite(dz)&(dz<=threshold)]
    if len(accepted)<3:
        raise ValueError("Insufficient supported ground seeds.")
    from .lidar_science import _ground
    ground=_ground(p,p[accepted],radius*2)
    height=p[:,2]-ground
    valid=np.isfinite(height)
    # Unknown points are not silently assigned to the nonground class.
    label=np.where(valid,(np.abs(height)<=threshold).astype(float),np.nan)
    return np.column_stack((p,ground,height,label)),{"seed_cells":len(keys),"accepted_seeds":len(accepted),
        "ground_points":int(np.nansum(label==1)),"nonground_points":int(np.nansum(label==0)),
        "unsupported_points":int((~valid).sum()),"slope_allowance":.35,"maximum_seed_neighbors":16}

def tin_mesh(p,max_edge):
    """2.5D TIN; triangles and their actual 3D area are exported."""
    xy,inv=np.unique(p[:,:2],axis=0,return_inverse=True)
    order=np.argsort(inv,kind="stable"); counts=np.bincount(inv)
    z=np.array([np.median(a) for a in np.split(p[order,2],np.cumsum(counts)[:-1])])
    vertices=np.column_stack((xy,z))
    try:tri=Delaunay(xy-xy.mean(axis=0)).simplices
    except QhullError as e:raise ValueError("TIN needs noncollinear XY coordinates.") from e
    v=vertices[tri]
    edges=np.linalg.norm(v-np.roll(v,1,axis=1),axis=2)
    keep=edges.max(axis=1)<=max_edge
    v=v[keep]
    if not len(v):raise ValueError("No triangles satisfy maximum 3D edge length.")
    cross=np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0])
    area=np.linalg.norm(cross,axis=1)/2
    projected=np.abs(cross[:,2])/2
    return np.column_stack((v.reshape(-1,9),area,projected)),{"triangles":len(v),"rejected_triangles":int((~keep).sum()),
        "surface_area_m2":float(area.sum()),"projected_area_m2":float(projected.sum()),
        "unique_xy_vertices":len(xy),"surface_type":"single-valued 2.5D TIN"}

def alpha_boundary(p,alpha):
    """Boundary triangles of the retained 3D Delaunay tetrahedra.

    Tetrahedra are retained when their circumsphere radius is <= alpha.
    This computes the boundary of the regularized volumetric alpha complex,
    not isolated lower-dimensional alpha simplices or Poisson reconstruction.
    """
    p=np.unique(p,axis=0)
    if not 4<=len(p)<=12000:raise ValueError("3D alpha boundary requires 4–12,000 unique points.")
    origin=p.mean(axis=0); q=p-origin
    try:tet=Delaunay(q).simplices
    except QhullError as e:raise ValueError("Alpha reconstruction needs noncoplanar points.") from e
    if len(tet)>300000:raise ValueError("Tetrahedral complexity budget exceeded.")
    v=q[tet];a=v[:,1:]-v[:,:1]
    rhs=np.sum(a*a,axis=2)/2
    sv=np.linalg.svd(a,compute_uv=False)
    valid=(sv[:,0]>0)&(sv[:,2]>sv[:,0]*1e-12)
    centers=np.linalg.solve(a[valid],rhs[valid,:,None])[:,:,0]
    keep=np.linalg.norm(centers,axis=1)<=alpha
    retained=tet[valid][keep]
    if not len(retained):raise ValueError("No tetrahedra satisfy alpha radius.")
    tv=q[retained]
    volume=np.abs(np.linalg.det(tv[:,1:]-tv[:,:1]))/6
    faces=np.concatenate([retained[:,[1,2,3]],retained[:,[0,2,3]],retained[:,[0,1,3]],retained[:,[0,1,2]]])
    opposite=np.concatenate([retained[:,i] for i in range(4)])
    _,inv,count=np.unique(np.sort(faces,axis=1),axis=0,return_inverse=True,return_counts=True)
    boundary=count[inv]==1
    faces=faces[boundary];opposite=opposite[boundary]
    v=p[faces]; n=np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0])
    flip=np.einsum("ij,ij->i",n,p[opposite]-v[:,0])>0
    v[flip]=v[flip][:,[0,2,1]]
    area=np.linalg.norm(n,axis=1)/2
    return np.column_stack((v.reshape(-1,9),area)),{"tetrahedra":len(retained),"boundary_faces":len(v),
        "volume_m3":float(volume.sum()),"surface_area_m2":float(area.sum()),"alpha_radius_m":alpha}

def plane_icp(source,reference,k,max_distance,trim,max_iterations,tolerance):
    """Robust point-to-plane ICP with Huber IRLS and explicit observability."""
    from .lidar_science import _local_geometry
    if len(reference)<k or len(source)<6:raise ValueError("Insufficient point-to-plane support.")
    origin=reference.mean(axis=0); ref=reference-origin; p=source-origin
    normals=_local_geometry(ref,k)[:,:3]
    valid=np.isfinite(normals).all(axis=1)
    if valid.sum()<6:raise ValueError("Insufficient valid reference normals.")
    ref=ref[valid]; normals=normals[valid];tree=cKDTree(ref)
    rot=np.eye(3);shift=np.zeros(3);history=[];converged=False
    for _ in range(max_iterations):
        d,idx=tree.query(p);use=np.flatnonzero(d<=max_distance)
        if len(use)<6:raise ValueError("Insufficient correspondences.")
        use=use[np.argsort(d[use],kind="stable")[:max(6,int(np.ceil(trim*len(use))))]]
        q=p[use]; n=normals[idx[use]];target=ref[idx[use]]
        residual=np.einsum("ij,ij->i",q-target,n)
        scale=max(1.4826*np.median(np.abs(residual-np.median(residual))),tolerance)
        w=np.minimum(1.,1.345*scale/np.maximum(np.abs(residual),1e-15))
        length=max(float(np.sqrt(np.mean(np.sum(q*q,axis=1)))),1e-6)
        a=np.column_stack((np.cross(q,n)/length,n))
        aw=a*np.sqrt(w[:,None]);b=-residual*np.sqrt(w)
        delta,_,rank,s=np.linalg.lstsq(aw,b,rcond=1e-10)
        if rank<6:raise ValueError("Point-to-plane alignment is not observable in all six rigid dimensions.")
        dr=Rotation.from_rotvec(delta[:3]/length).as_matrix();dt=delta[3:]
        updated=p@dr.T+dt
        step=float(np.sqrt(np.mean(np.sum((updated[use]-p[use])**2,axis=1))))
        p=updated;rot=dr@rot;shift=dr@shift+dt
        history.append(float(np.sqrt(np.mean(residual**2))))
        if step<=tolerance:converged=True;break
    d,idx=tree.query(p);inlier=d<=max_distance
    signed=np.einsum("ij,ij->i",p-ref[idx],normals[idx])
    return np.column_stack((p+origin,d,signed,inlier)),{"iterations":len(history),"converged":converged,
        "rotation_matrix":rot.tolist(),"translation_m":(origin+shift-rot@origin).tolist(),
        "condition_number":float(s[0]/s[-1]),"inlier_fraction":float(inlier.mean()),
        "plane_rmse_m":float(np.sqrt(np.mean(signed[inlier]**2))) if inlier.any() else None,
        "rmse_history_m":history}

def roof_planes(p,threshold,min_neighbors,max_iterations,k):
    """Sequential deterministic RANSAC planes with orthogonal TLS refinement.

    Planes are geometric candidates only; no semantic building label is asserted.
    """
    if threshold<=0 or min_neighbors<3:raise ValueError("Invalid plane threshold or support.")
    if len(p)>30000:raise ValueError("Plane extraction limit is 30,000 points; voxelize first.")
    rng=np.random.default_rng(42);remaining=np.arange(len(p));labels=np.full(len(p),-1)
    residuals=np.full(len(p),np.nan);normals=np.full((len(p),3),np.nan)
    results=[]
    for label in range(min(k,32)):
        if len(remaining)<min_neighbors:break
        xyz=p[remaining];origin=xyz.mean(axis=0);q=xyz-origin
        best=None
        for _ in range(max_iterations):
            a,b,c=q[rng.choice(len(q),3,replace=False)]
            n=np.cross(b-a,c-a);length=np.linalg.norm(n)
            if length<1e-12:continue
            n/=length
            dist=np.abs((q-a)@n)
            candidate=dist<=threshold
            if best is None or candidate.sum()>best.sum():best=candidate
        if best is None or best.sum()<min_neighbors:break
        fit=q[best];center=fit.mean(axis=0);_,s,vt=np.linalg.svd(fit-center,full_matrices=False)
        if s[1]<=s[0]*1e-12:break
        n=vt[-1]
        if n[2]<0:n=-n
        dist=np.abs((q-center)@n);keep=dist<=threshold
        if keep.sum()<min_neighbors:break
        ii=remaining[keep];labels[ii]=label;residuals[ii]=dist[keep];normals[ii]=n
        results.append({"id":label,"count":len(ii),"normal":n.tolist(),"rmse_m":float(np.sqrt(np.mean(dist[keep]**2))),
            "inclination_deg":float(np.degrees(np.arccos(np.clip(abs(n[2]),0,1))))})
        remaining=remaining[~keep]
    return np.column_stack((p,labels,residuals,normals)),{"planes":results,"unassigned_points":len(remaining),"seed":42}

def crown_candidates(p,ground,size,radius,threshold):
    """Ground-normalized CHM local maxima with nearest-apex XY assignment.

    Sparse grid cells are not filled; this is candidate tree delineation, not
    species-specific or validated individual-tree detection.
    """
    h=p[:,2]-ground;valid=np.isfinite(h)&(h>=threshold)
    if not valid.any():raise ValueError("No supported vegetation returns above threshold.")
    points=p[valid];height=h[valid]
    keys,inv=np.unique(np.floor(points[:,:2]/size).astype(np.int64),axis=0,return_inverse=True)
    top=np.full(len(keys),-np.inf);np.maximum.at(top,inv,height)
    xy=(keys+.5)*size;tree=cKDTree(xy)
    order=np.lexsort((keys[:,1],keys[:,0],-top))
    suppressed=np.zeros(len(keys),bool);apices=[]
    for i in order:
        if suppressed[i]:continue
        apices.append(i)
        suppressed[tree.query_ball_point(xy[i],radius)]=True
    apex=xy[apices];d,idx=cKDTree(apex).query(points[:,:2])
    assigned=d<=radius
    labels=np.full(len(p),np.nan);labels[valid]=np.where(assigned,idx,-1)
    # Return apex height and assignment for each supported point, without claiming crown area.
    apex_height=np.full(len(p),np.nan);apex_height[valid]=np.where(assigned,top[np.array(apices)[idx]],np.nan)
    return np.column_stack((p,h,labels,apex_height)),{"candidate_apices":len(apices),
        "assigned_returns":int(assigned.sum()),"unassigned_vegetation_returns":int((~assigned).sum()),
        "unsupported_ground_returns":int((~np.isfinite(h)).sum()),"apex_minimum_spacing_m":radius}
