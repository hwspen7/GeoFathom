"""P1 scientific terrain kernels: deterministic hydrology, fitted curvature,
grade-constrained design, coverage optimization, and seam-aligned 3-D LOD.

All inputs are projected metric grids. The source DEM is never mutated; invalid
pixels cannot silently act as known elevation or hydrological contributing area.
Scientific products remain provisional until independently validated.
"""
import math
from heapq import heappush, heappop

import numpy as np
from imagery.raster import RasterError
from .cancellation import checkpoint

# Counterclockwise from east, in projected metres (array rows increase south).
_DIR=((0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1),(1,0),(1,1))


def _validated(z,valid,dx,dy,budget=1_000_000):
    z=np.asarray(z,dtype=np.float64)
    valid=np.asarray(valid,dtype=bool)
    if z.ndim!=2 or z.shape!=valid.shape or not valid.any() or z.size>budget:
        raise RasterError("P1 requires a nonempty 2-D aligned grid within its memory budget.")
    if not (math.isfinite(dx) and math.isfinite(dy) and dx>0 and dy>0):
        raise RasterError("P1 requires positive projected metric grid spacing.")
    if not np.isfinite(z[valid]).all():
        raise RasterError("P1 valid elevations must be finite.")
    return z,valid


def dinfinity_accumulation(z,valid,dx,dy,external_inflow=None,cancel=None):
    """Tarboton eight triangular facets, at most two downhill recipients.

    Flow direction is the facet's steepest descent, angle CCW from east.
    An external source is supplied as nonnegative *cell equivalents* on
    explicitly measured inlet pixels; unknown upstream area is never inferred.
    """
    z,valid=_validated(z,valid,dx,dy)
    inflow=np.zeros(z.shape,dtype=np.float64)
    if external_inflow is not None:
        inflow=np.asarray(external_inflow,dtype=np.float64).copy()
        if inflow.shape!=z.shape or not np.isfinite(inflow).all() or (inflow<0).any() or (inflow[~valid]!=0).any():
            raise RasterError("External inflow must be nonnegative finite cell equivalents at valid cells.")
    h,w=z.shape
    acc=np.where(valid,1+inflow,np.nan)
    angles=np.full(z.shape,np.nan)
    nodes=np.flatnonzero(valid.ravel())
    nodes=nodes[np.argsort(z.ravel()[nodes],kind="stable")[::-1]]
    facets=[]
    for j,(dr1,dc1) in enumerate(_DIR):
        dr2,dc2=_DIR[(j+1)%8]
        x1,y1=dc1*dx,-dr1*dy
        x2,y2=dc2*dx,-dr2*dy
        determinant=x1*y2-x2*y1
        a1=math.atan2(y1,x1)%(2*math.pi)
        a2=math.atan2(y2,x2)%(2*math.pi)
        facets.append((dr1,dc1,dr2,dc2,x1,y1,x2,y2,determinant,a1,a2,
                       (a2-a1)%(2*math.pi),math.hypot(x1,y1),math.hypot(x2,y2)))
    for k,index in enumerate(nodes):
        if k%1024==0:checkpoint(cancel)
        r,c=divmod(int(index),w);base=z[r,c]
        best_slope=0.;best_angle=float("nan");best_targets=()
        for dr1,dc1,dr2,dc2,x1,y1,x2,y2,det,a1,a2,arc,d1,d2 in facets:
            r1,c1=r+dr1,c+dc1;r2,c2=r+dr2,c+dc2
            if not(0<=r1<h and 0<=c1<w and 0<=r2<h and 0<=c2<w and valid[r1,c1] and valid[r2,c2]):
                continue
            if (dr1 and dc1 and not(valid[r,c1] and valid[r1,c])) or (dr2 and dc2 and not(valid[r,c2] and valid[r2,c])):
                continue
            delta1=float(z[r1,c1]-base);delta2=float(z[r2,c2]-base)
            east=-(delta1*y2-delta2*y1)/det
            north=-(x1*delta2-x2*delta1)/det
            angle=math.atan2(north,east)%(2*math.pi)
            position=(angle-a1)%(2*math.pi)
            if position<=arc+1e-12:
                fraction=min(1.,max(0.,position/arc))
                t1=1-fraction if delta1<0 else 0.
                t2=fraction if delta2<0 else 0.
                total=t1+t2
                if total>0:
                    slope=math.hypot(east,north)
                    if slope>best_slope:
                        best_slope=slope;best_angle=angle
                        best_targets=tuple((i,p/total) for i,p in
                            ((r1*w+c1,t1),(r2*w+c2,t2)) if p>0)
            else:
                for delta,distance,bearing,rr,cc in ((delta1,d1,a1,r1,c1),(delta2,d2,a2,r2,c2)):
                    slope=max(0.,-delta/distance)
                    if slope>best_slope:
                        best_slope=slope;best_angle=bearing;best_targets=((rr*w+cc,1.),)
        if best_targets:
            angles[r,c]=best_angle
            for receiver,weight in best_targets:
                acc.ravel()[receiver]+=float(acc[r,c])*weight
    return acc,angles


def quadratic_curvature(z,valid,dx,dy,radius=2,kind="curvature",cancel=None,block=128):
    """Centered least-squares quadratic over 3x3 through 9x9 windows.

    Calculates physical first/second derivatives from normalized coordinates,
    avoiding cancellation from high absolute DEM elevations and large metres.
    Incomplete windows are NoData; directional curvature is undefined on flats.
    """
    z,valid=_validated(z,valid,dx,dy,8_000_000)
    if not isinstance(radius,int) or radius not in (1,2,3,4):
        raise RasterError("Quadratic fitting radius must be 1-4 cells.")
    if kind not in ("curvature","plan_curvature","profile_curvature"):
        raise RasterError("Unsupported fitted curvature component.")
    if min(z.shape)<2*radius+1:
        raise RasterError("DEM too small for quadratic fitting window.")
    axis=np.arange(-radius,radius+1,dtype=np.float64)/radius
    xx,yy=np.meshgrid(axis,axis)
    matrix=np.stack((np.ones_like(xx),xx,yy,xx*xx,xx*yy,yy*yy),axis=-1).reshape(-1,6)
    pinv=np.linalg.pinv(matrix,rcond=1e-12)
    result=np.full(z.shape,np.nan)
    width=2*radius+1;xscale=dx*radius;yscale=dy*radius
    for r in range(radius,z.shape[0]-radius,block):
        stop_r=min(z.shape[0]-radius,r+block)
        for c in range(radius,z.shape[1]-radius,block):
            checkpoint(cancel)
            stop_c=min(z.shape[1]-radius,c+block)
            tile=z[r-radius:stop_r+radius,c-radius:stop_c+radius]
            mask=valid[r-radius:stop_r+radius,c-radius:stop_c+radius]
            windows=np.lib.stride_tricks.sliding_window_view(tile,(width,width))
            complete=np.lib.stride_tricks.sliding_window_view(mask,(width,width)).all(axis=(-1,-2))
            center=z[r:stop_r,c:stop_c]
            diff=np.where(complete[...,None,None],windows-center[...,None,None],0.)
            coefficients=(diff.reshape(-1,width*width)@pinv.T).reshape(stop_r-r,stop_c-c,6)
            gx=coefficients[...,1]/xscale;gy=coefficients[...,2]/yscale
            gxx=2*coefficients[...,3]/xscale**2
            gxy=coefficients[...,4]/(xscale*yscale)
            gyy=2*coefficients[...,5]/yscale**2
            sq=gx*gx+gy*gy
            if kind=="curvature":
                answer=gxx+gyy
            else:
                with np.errstate(invalid="ignore",divide="ignore"):
                    if kind=="profile_curvature":
                        answer=(gx*gx*gxx+2*gx*gy*gxy+gy*gy*gyy)/(sq*(1+sq)**1.5)
                    else:
                        answer=(gy*gy*gxx-2*gx*gy*gxy+gx*gx*gyy)/sq**1.5
                answer=np.where(sq>1e-12,answer,np.nan)
            result[r:stop_r,c:stop_c]=np.where(complete,answer,np.nan)
    if not np.isfinite(result).any():
        raise RasterError("No complete quadratic curvature windows.")
    return result


def design_surface(z,valid,dx,dy,reference,east_grade=0.,north_grade=0.,
                   sigma_z=0.,max_grade=.3):
    """Grade-constrained design plane and cut/fill uncertainty bounds.

    sigmaz is a supplied one-sigma *assumption*, not a calibration claim.
    Independent-error and fully-correlated-error totals are kept separate.
    """
    z,valid=_validated(z,valid,dx,dy,8_000_000)
    params=(reference,east_grade,north_grade,sigma_z,max_grade)
    if not all(map(math.isfinite,params)) or sigma_z<0 or not 0<max_grade<=1:
        raise RasterError("Invalid design-grade or elevation uncertainty.")
    if math.hypot(east_grade,north_grade)>max_grade+1e-12:
        raise RasterError("Designed plane exceeds maximum grade.")
    rows,cols=np.indices(z.shape)
    plane=reference+(cols-(z.shape[1]-1)/2)*dx*east_grade-(rows-(z.shape[0]-1)/2)*dy*north_grade
    diff=np.where(valid,z-plane,np.nan)
    area=dx*dy;count=int(valid.sum())
    cut=float(np.nansum(np.maximum(diff,0))*area)
    fill=float(np.nansum(np.maximum(-diff,0))*area)
    return diff,{
        "cut_m3":cut,"fill_m3":fill,"net_cut_m3":cut-fill,
        "design_east_grade":east_grade,"design_north_grade":north_grade,
        "design_max_grade":max_grade,"design_reference_m":reference,
        "assumed_elevation_sigma_m":sigma_z,
        "net_volume_independent_sigma_m3":sigma_z*area*math.sqrt(count),
        "net_volume_correlated_sigma_m3":sigma_z*area*count,
        "covered_grid_area_m2":area*count}


def greedy_coverage(visible_masks,known_masks,max_sites,cancel=None):
    """Deterministic greedy maximum coverage with a common known-cell universe."""
    if not visible_masks or len(visible_masks)!=len(known_masks) or not 1<=max_sites<=len(visible_masks):
        raise RasterError("Coverage optimization needs valid candidate observations.")
    shape=np.asarray(visible_masks[0]).shape
    if len(shape)!=2:raise RasterError("Viewshed masks must be 2-D.")
    visible=[];known=[]
    for v,k in zip(visible_masks,known_masks):
        v=np.asarray(v,dtype=bool);k=np.asarray(k,dtype=bool)
        if v.shape!=shape or k.shape!=shape or (v&~k).any():
            raise RasterError("Coverage masks must match and visible must imply known.")
        visible.append(v);known.append(k)
    universe=np.logical_and.reduce(known)
    selected=[];gains=[];union=np.zeros(shape,dtype=bool)
    remaining=list(range(len(visible)))
    for _ in range(max_sites):
        checkpoint(cancel)
        gain=lambda index:int((visible[index]&universe&~union).sum())
        index=max(remaining,key=lambda i:(gain(i),-i))
        gains.append(gain(index));selected.append(index)
        union|=visible[index]&universe
        remaining.remove(index)
    return selected,gains,union


def mesh_lod_tiles(z,valid,dx,dy,tile_cells=32,levels=(1,2,4,8),cancel=None):
    """Globally aligned seam-sharing quadtree transport tiles.

    This supplies a mesh pyramid, not a claim of browser GPU streaming.
    Every coarse tile uses the same grid origin and preserves boundary nodes.
    """
    z,valid=_validated(z,valid,dx,dy,8_000_000)
    if tile_cells not in (16,32,64) or not levels or tuple(levels)!=tuple(sorted(set(levels))) or any(
        not isinstance(step,int) or step<1 or step&(step-1) for step in levels):
        raise RasterError("LOD tile steps must be sorted powers of two.")
    output=[];h,w=z.shape
    for step in levels:
        size=tile_cells*step
        for r0 in range(0,h-1,size):
            for c0 in range(0,w-1,size):
                checkpoint(cancel)
                r1=min(h-1,r0+size);c1=min(w-1,c0+size)
                rows=list(range(r0,r1+1,step));cols=list(range(c0,c1+1,step))
                if rows[-1]!=r1:rows.append(r1)
                if cols[-1]!=c1:cols.append(c1)
                elevations=z[np.ix_(rows,cols)];mask=valid[np.ix_(rows,cols)]
                if not mask.any():continue
                output.append({
                    "lod_step":step,"row_start":r0,"col_start":c0,
                    "rows":len(rows),"cols":len(cols),
                    "bounds_cell":[r0,c0,r1,c1],
                    "row_indices":rows,"col_indices":cols,
                    "heights":[float(value) if ok else None for value,ok in zip(elevations.flat,mask.flat)]})
    return output


def breach_depressions(z,valid,dx,dy,max_pits=64,max_cut_m=100.,cancel=None):
    """Bounded least-excavation channel search from interior pits to a lower outlet.

    Unlike priority-flood filling, excavation changes only a copied drainage
    channel. The cost model is an approximate least-cut path, not an audited
    earthworks optimization. A pit without a lower boundary outlet cannot be
    breached inside the available DEM and is reported as unresolved.
    """
    z,valid=_validated(z,valid,dx,dy,262_144)
    if not isinstance(max_pits,int) or not 1<=max_pits<=256 or not (
        math.isfinite(max_cut_m) and max_cut_m>0):
        raise RasterError("Invalid breach budget or maximum excavation depth.")
    h,w=z.shape;result=z.copy()
    outlets=np.zeros(z.shape,bool)
    outlets[0,:]=valid[0,:];outlets[-1,:]=valid[-1,:]
    outlets[:,0]=valid[:,0];outlets[:,-1]=valid[:,-1]
    for r in range(1,h-1):
        for c in range(1,w-1):
            if valid[r,c] and any(not valid[r+dr,c+dc] for dr,dc in _DIR):
                outlets[r,c]=True
    # Work only on true interior sinks, not on unknown DEM boundaries.
    pits=[]
    for r in range(1,h-1):
        for c in range(1,w-1):
            if not valid[r,c] or outlets[r,c]:continue
            neighbors=[]
            for dr,dc in _DIR:
                rr,cc=r+dr,c+dc
                if valid[rr,cc] and (not(dr and dc) or (valid[r,cc] and valid[rr,c])):
                    neighbors.append(result[rr,cc])
            if neighbors and min(neighbors)>=result[r,c]:
                pits.append((r,c))
    if len(pits)>max_pits:
        raise RasterError("Too many pits for bounded breaching; use priority-flood conditioning.")
    cut_total=0.;max_cut=0.;carved=set();unresolved=0
    for pit_r,pit_c in pits:
        checkpoint(cancel)
        start=pit_r*w+pit_c;start_z=float(result[pit_r,pit_c])
        frontier=[(0.,0,start)];best={start:(0.,0)};parent={}
        endpoint=None
        # Search channels minimizing cut cost plus a small path-length penalty.
        while frontier:
            cost,steps,index=heappop(frontier)
            if best.get(index)!=(cost,steps):continue
            r,c=divmod(index,w)
            if outlets[r,c] and result[r,c]<start_z:
                endpoint=index;break
            for dr,dc in _DIR:
                rr,cc=r+dr,c+dc
                if not(0<=rr<h and 0<=cc<w and valid[rr,cc]):continue
                if dr and dc and not(valid[r,cc] and valid[rr,c]):continue
                target=start_z-(steps+1)*1e-6
                cut=max(0.,float(result[rr,cc])-target)
                if cut>max_cut_m:continue
                next_cost=cost+cut*math.hypot(dc*dx,dr*dy)+.001*math.hypot(dc*dx,dr*dy)
                nxt=rr*w+cc;next_state=(next_cost,steps+1)
                if nxt not in best or next_state<best[nxt]:
                    best[nxt]=next_state;parent[nxt]=index
                    heappush(frontier,(next_cost,steps+1,nxt))
            if len(best)>262_144:break
            if len(best)%2048==0:checkpoint(cancel)
        if endpoint is None:
            unresolved+=1;continue
        path=[endpoint]
        while path[-1]!=start:path.append(parent[path[-1]])
        path.reverse()
        previous=start_z
        for j,index in enumerate(path[1:],1):
            r,c=divmod(index,w)
            desired=start_z+(float(result.flat[endpoint])-start_z)*j/(len(path)-1)
            next_height=min(float(result[r,c]),desired,previous-1e-6)
            difference=float(result[r,c])-next_height
            cut_total+=difference;max_cut=max(max_cut,difference)
            result[r,c]=next_height;previous=next_height;carved.add(index)
    return result,{
        "breached_pits":len(pits)-unresolved,
        "unresolved_pits":unresolved,
        "breach_carved_cells":len(carved),
        "breach_total_excavation_depth_m":cut_total,
        "breach_maximum_cut_m":max_cut,
    }


def weighted_suitability(z,valid,slope_deg,tri,max_slope,min_z,max_z,max_tri,
                         weights=(.5,.25,.25),sigma_z=0.):
    """Weighted linear combination after hard physical exclusion criteria.

    The scores [0,1] are ordinal utility ratings, *not probabilities*.
    Elevation preference peaks at the midpoint of the declared band; slope
    and TRI prefer small values. Invalid derivative neighborhoods are NoData.
    """
    z=np.asarray(z,dtype=np.float64)
    valid=np.asarray(valid,dtype=bool)
    slope=np.asarray(slope_deg,dtype=np.float64)
    tri=np.asarray(tri,dtype=np.float64)
    weights=np.asarray(weights,dtype=np.float64)
    if z.ndim!=2 or z.shape!=valid.shape or slope.shape!=z.shape or tri.shape!=z.shape:
        raise RasterError("Weighted suitability requires aligned 2-D derivative grids.")
    if weights.shape!=(3,) or not np.isfinite(weights).all() or (weights<0).any() or weights.sum()<=0:
        raise RasterError("Weighted suitability needs three nonnegative finite weights with a positive sum.")
    if not all(map(math.isfinite,(max_slope,min_z,max_z,max_tri,sigma_z))) or not (
        0<=max_slope<=90 and min_z<=max_z and max_tri>=0 and sigma_z>=0):
        raise RasterError("Weighted suitability has invalid hard thresholds or elevation uncertainty.")
    good=valid&np.isfinite(z)&np.isfinite(slope)&np.isfinite(tri)
    if not good.any():raise RasterError("No valid cells for weighted suitability.")
    permitted=good&(slope<=max_slope)&(z>=min_z)&(z<=max_z)&(tri<=max_tri)
    slope_utility=1-np.clip(slope/max(max_slope,1e-12),0,1)
    tri_utility=1-np.clip(tri/max(max_tri,1e-12),0,1)
    midpoint=(min_z+max_z)/2
    elevation_utility=1-np.clip(np.abs(z-midpoint)/max((max_z-min_z)/2,1e-12),0,1)
    normalized=weights/weights.sum()
    rating=(normalized[0]*slope_utility+normalized[1]*tri_utility+
            normalized[2]*elevation_utility)
    score=np.where(good,np.where(permitted,rating,0.),np.nan)
    # Loose per-cell utility bound induced only by the explicitly assumed
    # elevation uncertainty; this is not a confidence interval.
    elevation_error=normalized[2]*sigma_z/max((max_z-min_z)/2,1e-12)
    finite_values=score[np.isfinite(score)]
    return score,{
        "suitability_model_weighted":1,
        "suitable_area_m2":float(permitted.sum()),  # Caller scales by grid area.
        "suitable_pct":float(100*permitted.sum()/max(1,good.sum())),
        "mean_weighted_score":float(finite_values.mean()),
        "weighted_score_uncertainty_bound":float(min(1,elevation_error)),
        "score_weight_slope":float(normalized[0]),
        "score_weight_tri":float(normalized[1]),
        "score_weight_elevation":float(normalized[2]),
    }
