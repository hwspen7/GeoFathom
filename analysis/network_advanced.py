"""Exact bounded Pareto routing and correlated spatial hazard scenarios."""
from dataclasses import dataclass
from heapq import heappop,heappush
import math
import numpy as np
from .network_science import require,number,GEOD,partial

@dataclass
class Label:
    node:str
    first:float
    second:float
    prev:int|None
    edge:str|None
    active:bool=True

def pareto_routes(g,a,secondary,source,target):
    require(source!=target,'Select distinct origin and destination.')
    labels=[Label(source,0.,0.,None,None)];front={u:[] for u in a};front[source]=[0];queue=[(0.,0.,0)]
    comparisons=0
    while queue:
        _,_,i=heappop(queue);old=labels[i]
        if not old.active or old.node==target:continue
        for v,c,e in a[old.node]:
            x=old.first+c;y=old.second+secondary[e]
            require(x>old.first and y>old.second,'Costs exceed numeric dynamic range.')
            # A known target label can prune only when both accumulated
            # objectives already dominate the new label (all costs positive).
            candidates=front[v]+(front[target] if v!=target else [])
            comparisons+=len(candidates);require(comparisons<=2_000_000,'Exact Pareto comparison budget exceeded; reduce graph.')
            if any(labels[j].active and labels[j].first<=x and labels[j].second<=y for j in candidates):continue
            for j in front[v]:
                q=labels[j]
                if q.active and x<=q.first and y<=q.second:q.active=False
            front[v]=[j for j in front[v] if labels[j].active]
            require(len(front[v])<256 and len(labels)<50000,'Exact Pareto label budget exceeded; no approximate pruning applied.')
            j=len(labels);labels.append(Label(v,x,y,i,e));front[v].append(j);heappush(queue,(x,y,j))
    routes=[]
    for i in sorted(front[target],key=lambda j:(labels[j].first,labels[j].second)):
        q=labels[i];path=[];j=i
        while labels[j].prev is not None:
            cur=labels[j];parent=labels[cur.prev];path.append((parent.node,cur.node,cur.edge));j=cur.prev
        routes.append((q.first,q.second,list(reversed(path))))
    return routes,{'generated_labels':len(labels),'dominance_comparisons':comparisons,'tie_policy':'One deterministic representative per exactly equal objective pair.'}

def spatial_failure_draws(g,selected,prob,rng,trials,range_m):
    from scipy.special import ndtri
    require(len(selected)<=256,'Correlated reliability supports at most 256 uncertain edges.')
    by_id={e.id:e for e in g.edges};xyz=[]
    for eid in selected:
        lon,lat=partial(by_id[eid].coords,.5)[-1];lon,lat=math.radians(lon),math.radians(lat)
        xyz.append([6371008.8*math.cos(lat)*math.cos(lon),6371008.8*math.cos(lat)*math.sin(lon),6371008.8*math.sin(lat)])
    xyz=np.asarray(xyz);d=np.linalg.norm(xyz[:,None]-xyz[None,:],axis=2)
    covariance=np.exp(-d/range_m)
    eigen,v=np.linalg.eigh(covariance);require(eigen.min()>=-1e-8,'Spatial covariance is not positive semidefinite.')
    factor=v*np.sqrt(np.maximum(eigen,0))
    z=rng.standard_normal((trials,len(selected)))@factor.T
    return z<ndtri(prob),{'spatial_range_m':range_m,'latent_covariance':'Exponential of negative spherical chord distance between geodesic edge midpoints divided by range.',
        'maximum_off_diagonal_latent_correlation':float(np.max(covariance-np.eye(len(selected)))),
        'failure_model':'Gaussian copula with supplied marginal Bernoulli failure probabilities; latent correlation is not the binary correlation. Model is conditional, not calibrated hazard risk.'}

def raster_costs(g,exposure,reference,scale,alpha,coverage):
    require(all(c>=coverage and m is not None for m,_,c,_ in exposure.values()),'Insufficient raster coverage for impedance; unknown edges cannot be assigned safe cost.')
    out={}
    for e in g.edges:
        m=exposure[e.id][0];exponent=alpha*max(0.,(m-reference)/scale)
        require(exponent<=math.log(1000),'Raster impedance multiplier exceeds 1000; revise the physical scale.')
        out[e.id]=math.exp(exponent)
    return out
