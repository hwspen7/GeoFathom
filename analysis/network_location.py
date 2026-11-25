"""Finite candidate facility location and lexicographic capacitated allocation."""
from itertools import combinations
import math
import numpy as np
from .network_science import require

def location(ds,origins,destinations,demand,threshold,k,kind):
    require(1<=k<=len(destinations)<=24,'Choose 1–24 candidate facilities and a feasible facility count.')
    combinations_count=math.comb(len(destinations),k)
    require(combinations_count*len(origins)*k<=5_000_000,'Exact facility enumeration work budget exceeded.')
    candidates=sorted(destinations);best=None;selected=None;assignment=None;feasible=0
    for group in combinations(candidates,k):
        nearest=[]
        for s in origins:
            z,t=min((ds[s].get(t,math.inf),t) for t in group)
            nearest.append((s,t,z))
        if kind=='p_median':
            if any(not math.isfinite(z) for _,_,z in nearest):continue
            score=sum(demand[s]*z for s,_,z in nearest)
        else:score=-sum(demand[s] for s,_,z in nearest if z<=threshold)
        feasible+=1
        if best is None or score<best:best=score;selected=group;assignment=nearest
    require(selected is not None,'No facility set reaches all positive demand; use maximum coverage or revise candidates.')
    rows=[]
    for s,t,z in assignment:
        covered=math.isfinite(z) and (kind=='p_median' or z<=threshold)
        rows.append([s,t if covered else None,z if covered else None,demand[s],covered])
    total=sum(demand.values());covered=sum(r[3] for r in rows if r[4])
    return rows,{'selected_facilities':list(selected),'candidate_combinations':combinations_count,'feasible_combinations':feasible,
        'covered_demand':covered,'total_demand':total,'covered_fraction':covered/total,
        'objective':float(best if kind=='p_median' else -best),'tie_policy':'First lexicographically sorted facility set at exact objective tie; uncapacitated model.'}

def allocate(ds,origins,destinations,demand,supply,threshold):
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix,csr_matrix
    arcs=[(i,j,ds[s][t]) for i,s in enumerate(origins) for j,t in enumerate(destinations) if t in ds[s] and ds[s][t]<=threshold]
    total=sum(demand.values());capacity=sum(supply.values());scale=max(total,capacity)
    require(scale>0 and min([*demand.values(),*supply.values()])/scale>=1e-9,'Capacity or demand dynamic range is too large for LP feasibility tolerances.')
    if not arcs:return [],{'served_demand':0.,'unserved_demand':total,'available_capacity':capacity,'unused_capacity':capacity,'total_transport_cost':0.}
    n=len(arcs);index=np.arange(n);m=len(origins)
    matrix=coo_matrix((np.ones(2*n),(np.r_[[i for i,_,_ in arcs],[m+j for _,j,_ in arcs]],np.r_[index,index])),shape=(m+len(destinations),n)).tocsr()
    limits=np.array([demand[s] for s in origins]+[supply[t] for t in destinations])/scale
    opts={'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9}
    first=linprog(-np.ones(n),A_ub=matrix,b_ub=limits,bounds=(0,None),method='highs',options=opts)
    require(first.success,'Maximum served-demand LP did not converge.')
    served=float(first.x.sum());cost=np.array([z for _,_,z in arcs]);cost_scale=max(1.,float(cost.max()))
    second=linprog(cost/cost_scale,A_ub=matrix,b_ub=limits,A_eq=csr_matrix(np.ones((1,n))),b_eq=[served],bounds=(0,None),method='highs',options=opts)
    require(second.success,'Minimum-cost allocation LP did not converge.')
    flow=np.maximum(second.x,0);require(np.max(matrix@flow-limits)<=2e-9 and abs(flow.sum()-served)<=2e-9,'Allocation failed independent feasibility check.')
    rows=[[origins[i],destinations[j],float(q*scale),z,float(q*scale*z)] for (i,j,z),q in zip(arcs,flow) if q>0]
    delivered=float(flow.sum()*scale)
    return rows,{'served_demand':delivered,'unserved_demand':max(0.,total-delivered),'available_capacity':capacity,'unused_capacity':max(0.,capacity-delivered),
        'total_transport_cost':float(flow@cost*scale),'feasibility_tolerance_normalized':2e-9,'solver':'HiGHS two-stage linear programming: maximize served demand, then minimize transport cost at fixed maximum flow. Divisible demand, no indivisible household assignment.'}
