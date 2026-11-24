"""Directed connectivity and demand-weighted access distribution."""
import math
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_flow, breadth_first_order
from .network_science import require, dijkstra

def directed_cut(a,source,target):
    """Unit capacity per directed arc, parallel arcs summed exactly.

    Opposite directions of one physical road are distinct directed arcs.
    The result is directed arc connectivity, not physical-road reliability.
    """
    require(source!=target,"Connectivity endpoints must differ.")
    ids=sorted(a);idx={u:i for i,u in enumerate(ids)};rows=[];cols=[]
    for u,arcs in a.items():
        for v,_,_ in arcs:
            if u!=v:rows.append(idx[u]);cols.append(idx[v])
    n=len(ids)
    cap=csr_matrix((np.ones(len(rows),dtype=np.int64),(rows,cols)),shape=(n,n))
    fit=maximum_flow(cap,idx[source],idx[target],method="dinic")
    residual=cap-fit.flow
    residual.eliminate_zeros()
    reachable=set(breadth_first_order(residual,idx[source],directed=True,return_predecessors=False))
    cut=[(u,v,e) for u,arcs in a.items() if idx[u] in reachable for v,_,e in arcs if idx[v] not in reachable]
    require(len(cut)==int(fit.flow_value),"Max-flow/min-cut certificate mismatch.")
    return cut,{"directed_arc_connectivity":int(fit.flow_value),"cut_arc_count":len(cut),
        "source_side_nodes":len(reachable),"certificate":"integral unit-capacity max flow equals directed cut capacity"}

def access_equity(a,origins,destinations,demand,threshold):
    """Demand-weighted nearest-facility accessibility, retaining isolation.

    Score is 1/(1+cost/threshold) if reachable, zero otherwise. The threshold
    is a scale rather than a hard cutoff. Gini includes unreachable demand.
    """
    require(set(demand)==set(origins),"Provide positive demand for every origin.")
    rows=[]
    for s in origins:
        distances,_=dijkstra(a,s)
        cost,t=min(((distances[t],t) for t in destinations if t in distances),default=(None,None))
        score=1/(1+cost/threshold) if cost is not None else 0.
        rows.append([s,t,cost,demand[s],score])
    w=np.array([r[3] for r in rows],float);z=np.array([r[4] for r in rows],float)
    order=np.argsort(z,kind="stable");w=w[order];z=z[order]
    total=float(w.sum());mass=float(w@z)
    x=np.r_[0.,np.cumsum(w)/total]
    y=np.r_[0.,np.cumsum(w*z)/mass] if mass>0 else np.zeros(len(w)+1)
    gini=float(np.clip(1-np.sum(np.diff(x)*(y[1:]+y[:-1])),0,1)) if mass>0 else None
    return rows,{"demand_weighted_access":mass/total,"unreachable_demand_fraction":sum(r[3] for r in rows if r[2] is None)/total,
        "access_gini":gini,"cost_scale":threshold,"total_demand":total,
        "assumption":"nearest facility only; score is conditional accessibility utility, not probability or supply allocation"},[[float(a),float(b)] for a,b in zip(x,y)]
