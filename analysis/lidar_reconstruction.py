"""Bounded Poisson surface reconstruction and progressive TIN filtering."""
import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

def poisson_grid(points,k,spacing):
    """Padded uniform-grid Poisson approximation for closed star-shaped samples."""
    try:
        from skimage.measure import marching_cubes
    except ImportError as exc:
        raise ValueError("Poisson meshing requires the LiDAR extension.") from exc
    from .lidar_science import _local_geometry
    if len(points)<max(k,20):
        raise ValueError("Insufficient surface samples.")
    center=points.mean(axis=0)
    normals=_local_geometry(points,k)[:,:3]
    good=np.isfinite(normals).all(axis=1)
    if good.sum()<max(k,20):
        raise ValueError("Insufficient supported surface normals.")
    p=points[good];n=normals[good]
    n[np.einsum("ij,ij->i",n,p-center)<0]*=-1
    lo=p.min(axis=0)-4*spacing
    dims=(p.max(axis=0)-lo)/spacing+5
    if np.any(dims>192):
        raise ValueError("Poisson grid exceeds 192 cells per axis; increase spacing.")
    shape=np.ceil(dims).astype(int)
    if np.prod(shape,dtype=np.int64)>2_000_000:
        raise ValueError("Poisson grid exceeds two million cells; increase spacing.")
    if np.min(np.ptp(p,axis=0))<2*spacing:
        raise ValueError("Surface has insufficient three-dimensional extent.")
    pos=(p-lo)/spacing;base=np.floor(pos).astype(int);fraction=pos-base
    field=np.zeros((3,*shape),dtype=float)
    for a in (0,1):
        for b in (0,1):
            for c in (0,1):
                bit=np.array([a,b,c]);idx=base+bit
                weight=np.prod(np.where(bit,fraction,1-fraction),axis=1)
                for axis in range(3):
                    np.add.at(field[axis],tuple(idx.T),weight*n[:,axis])
    field=gaussian_filter(field,sigma=(0,1,1,1),mode="constant")
    div=sum((np.roll(field[i],-1,axis=i)-np.roll(field[i],1,axis=i))/(2*spacing) for i in range(3))
    freq=[-4*np.sin(np.pi*np.fft.fftfreq(int(m)))**2/spacing**2 for m in shape]
    lap=freq[0][:,None,None]+freq[1][None,:,None]+freq[2][None,None,:]
    rhs=np.fft.fftn(div);lap[0,0,0]=1;rhs[0,0,0]=0
    indicator=np.fft.ifftn(rhs/lap).real
    level=float(np.median(map_coordinates(indicator,pos.T,order=1,mode="nearest")))
    if not indicator.min()<level<indicator.max():
        raise ValueError("No supported Poisson isosurface.")
    vertices,faces,_,_=marching_cubes(indicator.astype(np.float32),level=level,spacing=(spacing,)*3,allow_degenerate=False)
    if len(faces)>200_000:
        raise ValueError("Poisson mesh exceeds face budget; increase spacing.")
    vertices=vertices.astype(float)+lo
    tri=vertices[faces]
    cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    area=np.linalg.norm(cross,axis=1)/2
    if np.einsum("ij,ij->i",cross,tri.mean(axis=1)-center).sum()<0:
        tri=tri[:,[0,2,1],:]
    edges=np.concatenate((faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]))
    _,count=np.unique(np.sort(edges,axis=1),axis=0,return_counts=True)
    return np.column_stack((tri.reshape(-1,9),area)),{
        "vertices":len(vertices),"triangles":len(faces),"surface_area_m2":float(area.sum()),
        "boundary_edges":int((count==1).sum()),"nonmanifold_edges":int((count>2).sum()),
        "normal_support":int(good.sum()),"grid_shape":shape.tolist(),"grid_spacing_m":spacing,
        "iso_level":level,"assumption":"closed approximately star-shaped surface; centroid-oriented normals"}

def progressive_tin(p,size,radius,threshold):
    """Coarse-to-fine lower-envelope TIN densification; no extrapolation."""
    from .lidar_science import _ground
    if radius<size or threshold<=0:
        raise ValueError("Initial cell must be at least final cell; threshold must be positive.")
    def lowest(cell,eligible):
        ix=np.flatnonzero(eligible)
        if not len(ix):return ix
        _,inv=np.unique(np.floor(p[ix,:2]/cell).astype(np.int64),axis=0,return_inverse=True)
        order=np.lexsort((p[ix,2],inv))
        return ix[order[np.r_[True,inv[order][1:]!=inv[order][:-1]]]]
    accepted=np.zeros(len(p),bool)
    accepted[lowest(radius,np.ones(len(p),bool))]=True
    if accepted.sum()<3:raise ValueError("Insufficient coarse seed points; reduce initial cell.")
    scales=sorted(set([radius,max(size,radius/2),max(size,radius/4),size]),reverse=True)
    history=[]
    for cell in scales[1:]:
        z=_ground(p,p[accepted],radius*3);residual=p[:,2]-z
        candidates=lowest(cell,~accepted&np.isfinite(residual)&(np.abs(residual)<=threshold))
        accepted[candidates]=True
        history.append({"cell_m":cell,"added_points":len(candidates),"seed_points":int(accepted.sum())})
    z=_ground(p,p[accepted],radius*3);h=p[:,2]-z
    valid=np.isfinite(h);label=np.where(valid,(np.abs(h)<=threshold).astype(float),np.nan)
    return np.column_stack((p,z,h,label)),{"accepted_seed_points":int(accepted.sum()),
        "ground_points":int(np.nansum(label==1)),"nonground_points":int(np.nansum(label==0)),
        "unsupported_points":int((~valid).sum()),"densification_history":history,
        "initial_cell_m":radius,"final_cell_m":size,"height_tolerance_m":threshold}
