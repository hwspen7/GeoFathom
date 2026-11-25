"""Terrain, canopy and urban structure estimators with explicit support."""
import numpy as np
from scipy.ndimage import distance_transform_edt, convolve, label
from scipy.spatial import cKDTree

def cloth_filter(p,size,radius,threshold,iterations,tolerance):
    """Inverted-height constrained membrane relaxation, CSF-inspired.

    The discrete cloth minimizes membrane strain plus a downward load subject
    to obstacle contact. This is not the canonical particle-spring CSF.
    """
    if radius<size or threshold<=0:
        raise ValueError("Cloth support radius must be at least one cell and tolerance positive.")
    key=np.floor(p[:,:2]/size).astype(np.int64)
    key-=key.min(axis=0)
    nx,ny=map(int,key.max(axis=0)+1)
    if nx*ny>1_000_000:
        raise ValueError("Cloth grid exceeds one million cells.")
    lowest=np.full((ny,nx),np.inf)
    np.minimum.at(lowest,(key[:,1],key[:,0]),p[:,2])
    observed=np.isfinite(lowest)
    dist,index=distance_transform_edt(~observed,return_indices=True)
    floor=-lowest[tuple(index)]
    support=dist*size<=radius
    cloth=np.full_like(floor,floor.max())
    kernel=np.array([[0.,1,0],[1,0,1],[0,1,0]])
    degree=convolve(support.astype(float),kernel,mode="constant")
    # Ignore unsupported nodes in the membrane stencil; no long-range bridge.
    load=.02*size
    converged=False
    for step in range(iterations):
        neighbors=convolve(np.where(support,cloth,0.),kernel,mode="constant")
        target=np.divide(neighbors-load,degree,out=cloth.copy(),where=degree>0)
        updated=np.where(support,np.maximum(floor,.5*cloth+.5*target),cloth)
        change=float(np.max(np.abs(updated[support]-cloth[support])))
        cloth=updated
        if change<=tolerance:
            converged=True;break
    estimate=-cloth[key[:,1],key[:,0]]
    residual=p[:,2]-estimate
    flags=(np.abs(residual)<=threshold).astype(float)
    return np.column_stack((p,estimate,residual,flags)),{
        "ground_points":int(flags.sum()),"nonground_points":int(len(p)-flags.sum()),
        "iterations":step+1,"converged":converged,"last_max_update_m":change,
        "grid_cells":nx*ny,"supported_cells":int(support.sum()),"load_m":load,
        "method":"CSF-inspired obstacle-constrained membrane; not canonical CSF"}

def canopy_complexity(p,ground,size,vertical,threshold):
    """Per-column return-height entropy and occupied above-ground voxel volume.

    The sampled return distribution is not leaf-area density or true biomass.
    """
    h=p[:,2]-ground
    good=np.isfinite(h)&(h>=threshold)
    if not good.any():raise ValueError("No supported returns above height threshold.")
    points=p[good];height=h[good]
    keys,inv,counts=np.unique(np.floor(points[:,:2]/size).astype(np.int64),axis=0,return_inverse=True,return_counts=True)
    order=np.argsort(inv,kind="stable")
    groups=np.split(height[order],np.cumsum(counts)[:-1])
    rows=[]
    for key,g in zip(keys,groups):
        bins,n=np.unique(np.floor(g/vertical).astype(np.int64),return_counts=True)
        prob=n/len(g);entropy=float(-np.sum(prob*np.log(prob)))
        rows.append([*(key+.5)*size,len(g),float(np.quantile(g,.95)),len(bins),
                     entropy,float(np.exp(entropy)),len(bins)*size**2*vertical,
                     float(np.max(g)-np.min(g))])
    table=np.asarray(rows)
    return table,{"columns":len(table),"supported_vegetation_returns":int(good.sum()),
        "unsupported_ground_returns":int((~np.isfinite(h)).sum()),
        "occupied_voxel_volume_m3":float(table[:,7].sum()),
        "horizontal_cell_m":size,"vertical_bin_m":vertical,
        "assumption":"observed voxel occupancy; no pulse-path or leaf-area inference"}

def building_candidates(p,ground,size,k,threshold,roughness,minimum):
    """Ground-normalized planar roof candidates and observed footprint metrics."""
    from .lidar_science import _local_geometry
    h=p[:,2]-ground
    elevated=np.isfinite(h)&(h>=threshold)
    if elevated.sum()<k:raise ValueError("Insufficient elevated points for roof candidate geometry.")
    q=p[elevated];height=h[elevated]
    geom=_local_geometry(q,k)
    valid=np.isfinite(geom[:,2])&(np.abs(geom[:,2])>=.5)&(geom[:,3]<=roughness)&(geom[:,4]>=.2)
    if not valid.any():raise ValueError("No supported planar roof candidates.")
    q=q[valid];height=height[valid]
    keys,inv,n=np.unique(np.floor(q[:,:2]/size).astype(np.int64),axis=0,return_inverse=True,return_counts=True)
    lo=keys.min(axis=0);ij=keys-lo
    nx,ny=map(int,ij.max(axis=0)+1)
    if nx*ny>1_000_000:raise ValueError("Roof grid exceeds one million cells.")
    roof=np.zeros((ny,nx),bool);roof[ij[:,1],ij[:,0]]=True
    components,count=label(roof,structure=np.array([[0,1,0],[1,1,1],[0,1,0]]))
    ids=components[ij[:,1],ij[:,0]]
    sizes=np.bincount(ids,minlength=count+1)
    keep=sizes[ids]>=minimum
    if not keep.any():raise ValueError("No roof component meets minimum occupied cells.")
    order=np.argsort(inv,kind="stable")
    med=np.array([np.median(g) for g in np.split(height[order],np.cumsum(n)[:-1])])
    z=np.array([np.median(g) for g in np.split(q[order,2],np.cumsum(n)[:-1])])
    degree=convolve(roof.astype(int),np.array([[0,1,0],[1,0,1],[0,1,0]]),mode="constant")
    boundary=(4-degree[ij[:,1],ij[:,0]])*size
    table=np.column_stack(((keys+.5)*size,z,med,ids,n,boundary))[keep]
    summaries=[]
    for component in np.unique(table[:,4])[:100]:
        t=table[table[:,4]==component]
        area=len(t)*size**2;perimeter=float(t[:,6].sum())
        summaries.append({"id":int(component),"observed_area_m2":area,"grid_perimeter_m":perimeter,
            "height_volume_proxy_m3":float(t[:,3].sum()*size**2),
            "compactness":float(4*np.pi*area/perimeter**2),
            "median_height_m":float(np.median(t[:,3]))})
    return table,{"candidate_components":len(np.unique(table[:,4])),"occupied_area_m2":len(table)*size**2,
        "height_volume_proxy_m3":float(table[:,3].sum()*size**2),
        "components":summaries,"roughness_limit_m":roughness,"minimum_cells":minimum,
        "assumption":"observed planar roof geometry only; not semantic building labels or true enclosed volume"}
