"""Reference-anchored weighted least-squares phase reconstruction."""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import lsmr
from analysis.science_raster import require

def reconstruct(v,p,kind):
    phase=v['phase'];coherence=v['coherence'];h,w=phase.shape
    valid=np.isfinite(phase)&np.isfinite(coherence)&(coherence>=p['min_coherence'])
    row,col=p['reference_row'],p['reference_col']
    require(row<h and col<w and valid[row,col],'Reference point must be a valid coherent pixel.')
    require(2<=valid.sum()<=30000,'Phase reconstruction requires 2–30,000 coherent cells.')
    def wrap(x):return np.arctan2(np.sin(x),np.cos(x))
    require(abs(wrap(p['reference_phase']-phase[row,col]))<=1e-6,'Reference phase is not congruent to wrapped phase.')
    ids=np.full(phase.shape,-1,dtype=int);ids[valid]=np.arange(int(valid.sum()))
    pairs=[]
    for a,b,ok,qa,qb in ((ids[:,:-1],ids[:,1:],valid[:,:-1]&valid[:,1:],coherence[:,:-1],coherence[:,1:]),(ids[:-1],ids[1:],valid[:-1]&valid[1:],coherence[:-1],coherence[1:])):
        pairs.append((a[ok],b[ok],np.minimum(qa[ok],qb[ok])))
    src,dst,weight=[np.concatenate(z) for z in zip(*pairs)]
    n=int(valid.sum());ref=ids[row,col]
    adj=coo_matrix((np.ones(len(src)),(src,dst)),shape=(n,n)).tocsr()
    _,components=connected_components(adj,directed=False)
    keep=components==components[ref];edge=keep[src]&keep[dst]
    require(keep.sum()>=2 and edge.any(),'Reference component contains no connected phase gradient.')
    phase_values=phase[valid];delta=wrap(phase_values[dst[edge]]-phase_values[src[edge]])
    src,dst,weight=src[edge],dst[edge],weight[edge];root=np.sqrt(weight)
    # Remove reference variable: the remaining system is full column rank
    # on the reference component. Solve for phase relative to that anchor.
    unknown=np.flatnonzero(keep & (np.arange(n)!=ref));index=np.full(n,-1,int);index[unknown]=np.arange(len(unknown))
    ii=np.arange(len(src));ls=src!=ref;ld=dst!=ref
    matrix=coo_matrix((np.r_[-root[ls],root[ld]],(np.r_[ii[ls],ii[ld]],np.r_[index[src[ls]],index[dst[ld]]])),shape=(len(src),len(unknown))).tocsr()
    require(len(src)*p['max_iterations']<=180_000_000,'Phase solver exceeds iteration work budget.')
    solution=lsmr(matrix,delta*root,atol=1e-10,btol=1e-10,maxiter=p['max_iterations'])
    require(solution[1] in (0,1,2,4,5),'Weighted phase reconstruction did not converge.')
    values=np.full(n,np.nan);values[ref]=0.;values[unknown]=solution[0]
    residual=values[dst]-values[src]-delta;absolute=values+p['reference_phase']
    circular=wrap(absolute[keep]-phase_values[keep])
    result=np.full(phase.shape,np.nan)
    if kind=='insar_relative_range':
        # Explicit phase convention; no inferred orbital/topographic removal.
        result[valid]=values*p['wavelength_m']/(4*np.pi)*p['range_sign']
    else:result[valid]=absolute
    return result,{'reference_component_cells':int(keep.sum()),'excluded_disconnected_cells':int((~keep).sum()),
        'weighted_gradient_rmse_rad':float(np.sqrt(np.average(residual**2,weights=weight))),
        'wrapped_consistency_rmse_rad':float(np.sqrt(np.mean(circular**2))),'iterations':int(solution[2]),
        'interpretation':'Reference-anchored weighted least-squares phase reconstruction. Can smooth inconsistent residues and need not be exactly congruent; inspect residual diagnostics. Range conversion requires externally removed orbital/topographic/atmospheric phase and explicit sign convention.'}
