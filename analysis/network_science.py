"""Bounded directed multigraph science, with explicit topology and native raster exposure."""
from collections import defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush
import base64
import csv
import hashlib
import io
import json
import math

from pyproj import Geod, Transformer

GEOD=Geod(ellps="WGS84")
METHODS={
 "topology":("Network structure","Topology and weak components; explicit endpoints, no automatic crossing intersection."),
 "shortest_path":("Least-cost path","Directed Dijkstra with positive additive costs; parallel edges retained."),
 "od_matrix":("Origin–destination costs","Directed origin–destination cost matrix; unreachable pairs are null."),
 "service_area":("Network service reach","Reachable nodes and partial edge segments; no fictitious polygon coverage."),
 "nearest_facility":("Nearest facility","Minimum directed origin-to-facility cost."),
 "gravity_access":("Gravity accessibility","Supply-weighted exponential impedance decay."),
 "two_step_fca":("Two-step floating catchment accessibility","Demand competition and facility supply within a directed cost threshold."),
 "harmonic_centrality":("Harmonic centrality","Directed outgoing inverse-cost centrality with unreachable nodes contributing zero."),
 "betweenness":("Weighted betweenness","Exact weighted Brandes node centrality including equal-cost parallel paths."),
 "scenario_impact":("Disruption and resilience","Compare baseline and scenario OD costs, isolation and detour impacts."),
 "circuity":("Geodesic network circuity","Distance-weighted network path divided by geodesic separation; unreachable pairs remain null."),
 "edge_criticality":("Single-edge disruption criticality","Exact one-at-a-time removal on selected edges and directed OD pairs; not simultaneous failures."),
 "stochastic_reliability":("Stochastic network reliability","Seeded independent edge-failure Monte Carlo; Wilson intervals quantify simulation error, not hazard-model uncertainty."),
 "hazard_exposure":("Raster edge exposure","Native raster sample mean, maximum and valid coverage along each edge.")
}

class NetworkError(ValueError):pass

def require(condition,message):
    if not condition:raise NetworkError(message)

def number(value,label,minimum=0,maximum=1e12):
    require(isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and minimum<=value<=maximum,label+" is outside the supported numeric range.")
    return float(value)

def point(raw):
    require(isinstance(raw,(list,tuple)) and len(raw)>=2,"Expected WGS84 coordinate pair.")
    return (number(raw[0],"Longitude",-180,180),number(raw[1],"Latitude",-90,90))

def node_id(value):
    require(isinstance(value,str) and 0<len(value)<=128 and value.strip()==value,"Node/edge IDs must be nonempty strings up to 128 characters.")
    return value

@dataclass(frozen=True)
class Edge:
    id:str
    source:str
    target:str
    coords:tuple
    length:float
    cost:float
    direction:str

class Graph:
    def __init__(self,collection,cost_field):
        require(collection.get("type")=="FeatureCollection" and isinstance(collection.get("features"),list),"Use a WGS84 GeoJSON FeatureCollection of pre-noded LineStrings.")
        features=collection["features"]
        require(1<=len(features)<=10000,"Use 1–10,000 input edges.")
        self.nodes={};self.edges=[];self.ids=set();vertices=0
        def register(key,xy):
            if key in self.nodes:require(self.nodes[key]==xy,"Same node ID has inconsistent endpoint coordinates: "+key)
            else:self.nodes[key]=xy
        for i,f in enumerate(features):
            require(isinstance(f,dict) and f.get("type")=="Feature","Invalid edge feature.")
            g=f.get("geometry");p=f.get("properties") or {}
            require(isinstance(g,dict) and g.get("type")=="LineString" and isinstance(p,dict),"Every edge must be a LineString with properties.")
            raw=g.get("coordinates")
            require(isinstance(raw,list) and 2<=len(raw)<=10000,"LineString requires 2–10,000 vertices.")
            vertices+=len(raw);require(vertices<=100000,"Network exceeds 100,000 input vertices.")
            coords=tuple(point(x) for x in raw)
            # Exact endpoint matching only. Explicit IDs can distinguish
            # coincident grade-separated junctions.
            def endpoint(name,xy):
                return node_id(p[name]) if name in p else "xy:"+format(xy[0],".17g")+","+format(xy[1],".17g")
            u,v=endpoint("source",coords[0]),endpoint("target",coords[-1])
            register(u,coords[0]);register(v,coords[-1])
            e=node_id(p.get("edge_id",str(i+1)));require(e not in self.ids,"Duplicate edge ID: "+e);self.ids.add(e)
            require(u!=v,"Self-loop edges require explicit segmentation into distinct junctions.")
            require(all(abs(a[0]-b[0])<=180 for a,b in zip(coords,coords[1:])),"Split antimeridian-crossing edges before analysis.")
            length=float(GEOD.line_length(*zip(*coords)));require(math.isfinite(length) and length>0,"Zero-length or invalid edge.")
            cost=length if cost_field=="length_m" else number(p.get(cost_field),"Edge cost",1e-8,1e12)
            direction=p.get("direction","both");require(direction in ("both","forward","reverse"),"Direction must be both, forward or reverse.")
            self.edges.append(Edge(e,u,v,coords,length,cost,direction))
        self.edges.sort(key=lambda e:e.id)
    def adjacency(self,closed=(),multipliers=None):
        a={u:[] for u in self.nodes};multipliers=multipliers or {}
        for e in self.edges:
            if e.id in closed:continue
            c=e.cost*multipliers.get(e.id,1)
            if e.direction in ("both","forward"):a[e.source].append((e.target,c,e.id))
            if e.direction in ("both","reverse"):a[e.target].append((e.source,c,e.id))
        return a

def reverse(a):
    r={u:[] for u in a}
    for u,arcs in a.items():
        for v,c,e in arcs:r[v].append((u,c,e))
    return r

def dijkstra(a,source,limit=math.inf):
    d={source:0.};prev={};queue=[(0.,source)]
    while queue:
        du,u=heappop(queue)
        if du!=d[u]:continue
        for v,c,e in a[u]:
            z=du+c;require(z>du,'Edge costs have excessive dynamic range for floating-point accumulation.')
            if z<=limit and z<d.get(v,math.inf):
                d[v]=z;prev[v]=(u,e);heappush(queue,(z,v))
    return d,prev

def components(a):
    r=reverse(a);seen=set();groups={};group=0
    for u in sorted(a):
        if u in seen:continue
        group+=1;stack=[u];seen.add(u)
        while stack:
            v=stack.pop();groups[v]=group
            for n,_,_ in a[v]+r[v]:
                if n not in seen:seen.add(n);stack.append(n)
    return groups

def brandes(a):
    # Strict positive weights and exact equal-cost ties; repeated predecessor
    # entries represent distinct parallel shortest edges.
    central={u:0. for u in a}
    for s in sorted(a):
        d={s:0.};sigma=defaultdict(int,{s:1});pred=defaultdict(list);q=[(0.,s)];order=[]
        while q:
            du,u=heappop(q)
            if du!=d[u]:continue
            order.append(u)
            for v,c,_ in a[u]:
                z=du+c;require(z>du,'Edge costs have excessive dynamic range for floating-point accumulation.')
                if z<d.get(v,math.inf):
                    d[v]=z;sigma[v]=sigma[u];pred[v]=[u];heappush(q,(z,v))
                elif z==d.get(v):sigma[v]+=sigma[u];pred[v].append(u)
        dep=defaultdict(float)
        for v in reversed(order):
            for u in pred[v]:dep[u]+=(sigma[u]/sigma[v])*(1+dep[v])
            if v!=s:central[v]+=dep[v]
    n=len(a);den=(n-1)*(n-2)
    return {u:central[u]/den if den>0 else 0. for u in a}

def partial(coords,fraction):
    if fraction>=1:return list(coords)
    length=GEOD.line_length(*zip(*coords));remaining=length*fraction;out=[coords[0]]
    for a,b in zip(coords,coords[1:]):
        az,_,dist=GEOD.inv(*a,*b)
        if dist<=0:continue
        if remaining>=dist:out.append(b);remaining-=dist
        else:
            x,y,_=GEOD.fwd(*a,az,remaining);out.append((x,y));break
    return out

def feature(geometry,**p):return {"type":"Feature","geometry":geometry,"properties":p}
def node_feature(g,u,**p):return feature({"type":"Point","coordinates":g.nodes[u]},node_id=u,**p)
def edge_feature(e,coords=None,**p):return feature({"type":"LineString","coordinates":list(e.coords if coords is None else coords)},edge_id=e.id,source=e.source,target=e.target,**p)

def raster_exposure(g,raster,spacing):
    import numpy as np
    from rasterio.io import MemoryFile
    raw=base64.b64decode(raster.data,validate=True);require(len(raw)<=12_000_000,"Raster exceeds 12 MB.")
    result={};total=0
    with MemoryFile(raw) as mem,mem.open() as ds:
        require(ds.driver=="GTiff" and ds.crs and 1<=raster.band<=ds.count and ds.width*ds.height<=4_000_000,"Use georeferenced GeoTIFF with at most four million cells.")
        band=ds.read(raster.band,masked=True).astype(float).filled(np.nan)
        scale,offset=float(ds.scales[raster.band-1]),float(ds.offsets[raster.band-1])
        require(math.isfinite(scale) and scale>0 and math.isfinite(offset),"Invalid raster calibration.")
        transform=Transformer.from_crs("EPSG:4326",ds.crs,always_xy=True)
        # Equal-distance midpoint samples along full geodesic chain. Each
        # edge contributes its own uniformly weighted samples.
        for e in g.edges:
            n=max(1,math.ceil(e.length/spacing));total+=n;require(total<=100000,"Raster sampling exceeds 100,000 points; increase spacing.")
            positions=[];segment=0;start=0.;coords=e.coords
            az,_,dist=GEOD.inv(*coords[0],*coords[1])
            for j in range(n):
                distance=(j+.5)*e.length/n
                while segment<len(coords)-2 and distance>start+dist:
                    start+=dist;segment+=1;az,_,dist=GEOD.inv(*coords[segment],*coords[segment+1])
                x,y,_=GEOD.fwd(*coords[segment],az,max(0,distance-start));positions.append((x,y))
            xx,yy=transform.transform(*zip(*positions));values=[]
            for x,y in zip(xx,yy):
                if not math.isfinite(x) or not math.isfinite(y):continue
                row,col=ds.index(x,y)
                if 0<=row<ds.height and 0<=col<ds.width:
                    z=band[row,col]*scale+offset
                    if math.isfinite(z):values.append(float(z))
            result[e.id]=(sum(values)/len(values) if values else None,max(values) if values else None,len(values)/n,n)
        return result,{"raster_sha256":hashlib.sha256(raw).hexdigest(),"raster_unit":ds.tags().get("TERRAIN_UNIT","unspecified"),"scale":scale,"offset":offset,"sampling":"Uniform geodesic midpoint samples, native nearest cells; not exact line integral or independent observations."}

def table_csv(cols,rows):
    s=io.StringIO();w=csv.writer(s);w.writerow(cols);w.writerows(rows);return s.getvalue()

def execute(body):
    serialized=json.dumps(body.network,sort_keys=True,separators=(',',':'),allow_nan=False)
    require(len(serialized.encode())<=8_000_000,'Network JSON exceeds 8 MB.')
    g=Graph(body.network,body.cost_field);a=g.adjacency();kind=body.operation
    require(kind in METHODS,"Unknown network method.")
    origins=body.origins;destinations=body.destinations
    for ids in (origins,destinations,list(body.demand),list(body.supply)):
        require(len(ids)==len(set(ids)) and set(ids)<=set(g.nodes),"Unknown or duplicated node ID.")
    for e,m in body.multipliers.items():require(e in g.ids and 1<=m<=1000,"Invalid edge multiplier.")
    require(set(body.closed_edges)<=g.ids,"Unknown closed edge ID.")
    require(not (body.closed_edges or body.multipliers) or kind=="scenario_impact","Closures and multipliers are scenario-only parameters.")
    require(not body.failure_probability or kind=="stochastic_reliability","Failure probabilities are reliability-only parameters.")
    require(not body.test_edges or kind=="edge_criticality","Selected test edges are criticality-only parameters.")
    require(set(body.failure_probability)<=g.ids and set(body.test_edges)<=g.ids and len(set(body.test_edges))==len(body.test_edges),"Unknown or duplicated scenario edge.")
    require(body.raster is None or kind in ("hazard_exposure","scenario_impact"),"Raster is accepted only for exposure and scenario analysis.")
    n=len(g.nodes);arcs=sum(map(len,a.values()));features=[];rows=[];metrics={};cols=[];figures=[]
    def plot(title,recipe,x,y,columns=None,values=None):
        csv_data=table_csv(cols,rows) if values is None else table_csv(*values)
        bindings={"x":x,"y":y}
        if columns:bindings["columns"]=columns
        figures.append({"title":title,"recipe":recipe,"bindings":bindings,"csv":csv_data,"raster":False})
    def budget(count):require(count*(n+arcs)<=10_000_000,"Network search work budget exceeded.")
    if kind=="topology":
        group=components(a);r=reverse(a);cols=["node","longitude","latitude","out_degree","in_degree","component"]
        rows=[[u,*g.nodes[u],len(a[u]),len(r[u]),group[u]] for u in sorted(g.nodes)]
        features=[edge_feature(e,cost=e.cost,length_m=e.length) for e in g.edges]
        metrics={"weak_components":len(set(group.values())),"isolated_nodes":sum(not a[u] and not r[u] for u in a)}
        counts=defaultdict(int)
        for v in a.values():counts[len(v)]+=1
        plot("Outgoing degree distribution","basic_column","degree","nodes",values=(["degree","nodes"],sorted(counts.items())))
    elif kind=="shortest_path":
        require(len(origins)==len(destinations)==1,"Choose one origin and one destination.")
        s,t=origins[0],destinations[0];d,prev=dijkstra(a,s);cols=["sequence","edge","from_node","to_node","edge_cost","cumulative_cost"]
        path=[];u=t;by_id={e.id:e for e in g.edges}
        if t in d:
            while u!=s:
                v,e=prev[u];path.append((v,u,e));u=v
            for i,(u,v,eid) in enumerate(reversed(path),1):
                e=by_id[eid];coords=e.coords if u==e.source else e.coords[::-1]
                rows.append([i,eid,u,v,e.cost,d[v]]);features.append(edge_feature(e,coords,sequence=i,cost=e.cost))
        metrics={"reachable":t in d,"total_cost":d.get(t),"route_length_m":sum(by_id[e].length for _,_,e in path) if t in d else None}
        if rows:plot("Cumulative route impedance","basic_line" if len(rows)>1 else "basic_column","sequence","cumulative_cost")
    elif kind=="service_area":
        require(1<=len(origins)<=64,"Choose service origins.");budget(len(origins))
        distance={}
        for s in origins:
            d,_=dijkstra(a,s,body.threshold)
            for u,z in d.items():distance[u]=min(z,distance.get(u,math.inf))
        cols=["node","cost"];rows=[[u,distance.get(u)] for u in sorted(g.nodes)]
        for e in g.edges:
            left=min(1,max(0,(body.threshold-distance.get(e.source,math.inf))/e.cost)) if e.direction!="reverse" else 0
            right=min(1,max(0,(body.threshold-distance.get(e.target,math.inf))/e.cost)) if e.direction!="forward" else 0
            if left+right>=1:features.append(edge_feature(e,reachable_fraction=1.))
            else:
                if left>0:features.append(edge_feature(e,partial(e.coords,left),reachable_fraction=left))
                if right>0:features.append(edge_feature(e,partial(e.coords[::-1],right),reachable_fraction=right))
        reach=sorted(distance.values());metrics={"reachable_nodes":len(reach),"reachable_length_m":sum(GEOD.line_length(*zip(*f["geometry"]["coordinates"])) for f in features),"threshold":body.threshold}
        plot("Network service reach curve","basic_line" if len(reach)>1 else "basic_column","cost","nodes",values=(["cost","nodes"],[[z,i+1] for i,z in enumerate(reach)]))
    elif kind in ("harmonic_centrality","betweenness"):
        budget(n);require(n<=2000,"Exact all-node centrality limited to 2,000 nodes.")
        scores=brandes(a) if kind=="betweenness" else {u:sum(1/z for v,z in dijkstra(a,u)[0].items() if v!=u)/(n-1) for u in a}
        cols=["node","score"];rows=[[u,scores[u]] for u in sorted(a)]
        features=[node_feature(g,u,score=scores[u]) for u in sorted(a)]
        ordered=sorted(scores.values(),reverse=True);plot("Centrality rank distribution","basic_line","rank","score",values=(["rank","score"],[[i+1,z] for i,z in enumerate(ordered)]))
    elif kind in ("edge_criticality","stochastic_reliability","circuity"):
        require(origins and destinations and len(origins)*len(destinations)<=10000,"Choose up to 10,000 OD pairs.")
        if kind=="circuity":require(body.cost_field=="length_m","Circuity requires geodesic edge length costs.")
        budget(len(origins))
        baseline={s:dijkstra(a,s)[0] for s in origins};pairs=[(s,t,baseline[s].get(t)) for s in origins for t in destinations]
        if kind=="circuity":
            cols=["origin","destination","network_distance_m","geodesic_distance_m","circuity"]
            for s,t,d in pairs:
                _,_,direct=GEOD.inv(*g.nodes[s],*g.nodes[t]);ratio=d/direct if d is not None and direct>1e-6 else None
                rows.append([s,t,d,direct,ratio])
            values=[r for r in rows if r[-1] is not None]
            metrics={"reachable_noncoincident_pairs":len(values),"mean_circuity":sum(r[-1] for r in values)/len(values) if values else None}
            if values:plot("Network versus geodesic distance","basic_scatter","geodesic_distance_m","network_distance_m",values=(cols[2:4],[r[2:4] for r in values]))
        elif kind=="edge_criticality":
            tested=body.test_edges or sorted(g.ids)
            require(len(tested)<=256,"Select at most 256 candidate edges.");budget(len(origins)*(len(tested)+1))
            connected=[(s,t,d) for s,t,d in pairs if d is not None]
            require(connected,"No baseline reachable pairs.")
            cols=["edge","lost_pairs","lost_fraction","mean_retained_detour","retained_pairs"]
            by_id={e.id:e for e in g.edges}
            for eid in tested:
                modified=g.adjacency({eid});dist={s:dijkstra(modified,s)[0] for s in origins}
                changes=[dist[s][t]-d for s,t,d in connected if t in dist[s]];lost=len(connected)-len(changes)
                mean=sum(changes)/len(changes) if changes else None
                rows.append([eid,lost,lost/len(connected),mean,len(changes)])
                features.append(edge_feature(by_id[eid],lost_fraction=lost/len(connected),mean_retained_detour=mean))
            rows.sort(key=lambda r:(-r[1],-(r[3] or 0),r[0]))
            metrics={"tested_edges":len(tested),"baseline_reachable_pairs":len(connected),"maximum_lost_fraction":max(r[2] for r in rows)}
            plot("Edge criticality by disconnected OD fraction","horizontal_bar","edge","lost_fraction")
        else:
            import numpy as np
            require(body.failure_probability,"Provide explicit independent failure probabilities for selected edges.")
            budget(len(origins)*(body.trials+1));require(len(pairs)*body.trials<=5_000_000,"Reliability simulation exceeds OD trial budget.")
            rng=np.random.default_rng(body.seed);selected=sorted(body.failure_probability);prob=np.array([body.failure_probability[e] for e in selected])
            success=np.zeros(len(pairs),dtype=np.int64);cost_sum=np.zeros(len(pairs))
            for _ in range(body.trials):
                closed={e for e,q in zip(selected,rng.random(len(selected))<prob) if q}
                modified=g.adjacency(closed);dist={s:dijkstra(modified,s)[0] for s in origins}
                for i,(s,t,d) in enumerate(pairs):
                    if t in dist[s]:success[i]+=1;cost_sum[i]+=dist[s][t]
            cols=["origin","destination","baseline","reachable_probability","wilson_low","wilson_high","conditional_cost"]
            z=1.959963984540054;T=body.trials
            for i,(s,t,d) in enumerate(pairs):
                p=float(success[i]/T);den=1+z*z/T;center=(p+z*z/(2*T))/den;half=z*math.sqrt(p*(1-p)/T+z*z/(4*T*T))/den
                rows.append([s,t,d,p,0. if p==0 else max(0,center-half),1. if p==1 else min(1,center+half),float(cost_sum[i]/success[i]) if success[i] else None])
            metrics={"trials":T,"seed":body.seed,"mean_pair_reliability":float(success.mean()/T),"failure_model":"Independent Bernoulli closures; Wilson intervals are Monte Carlo sampling intervals conditional on supplied probabilities."}
            plot("OD reliability and simulation intervals","errorbar","pair","reachable_probability",values=(["pair","reachable_probability","low","high"],[[i+1,r[3],r[4],r[5]] for i,r in enumerate(rows)]))
            figures[-1]["bindings"].update(low="low",high="high")
    elif kind=="hazard_exposure":
        require(body.raster is not None,"Provide an exposure raster.")
        exposure,meta=raster_exposure(g,body.raster,body.spacing_m);metrics.update(meta)
        cols=["edge","mean","maximum","coverage","samples"]
        for e in g.edges:
            m,z,c,k=exposure[e.id];rows.append([e.id,m,z,c,k]);features.append(edge_feature(e,mean=m,maximum=z,coverage=c))
        if any(r[1] is not None for r in rows):plot("Edge exposure and sample coverage","basic_scatter","coverage","mean",values=(["coverage","mean"],[[r[3],r[1]] for r in rows if r[1] is not None]))
    else:
        require(origins and destinations,"Choose origins and destinations.");require(len(origins)*len(destinations)<=10000,"OD table exceeds 10,000 pairs.")
        budget(len(origins)*(2 if kind=="scenario_impact" else 1))
        ds={s:dijkstra(a,s)[0] for s in origins}
        if kind=="scenario_impact":
            closed=set(body.closed_edges);multipliers=body.multipliers
            if body.raster is not None:
                exposure,meta=raster_exposure(g,body.raster,body.spacing_m);metrics.update(meta)
                require(all(c>=body.minimum_coverage and z is not None for _,z,c,_ in exposure.values()),"Insufficient raster coverage; no unknown edge is assumed safe.")
                closed.update(e for e,(_,z,_,_) in exposure.items() if z>=body.hazard_threshold)
            modified=g.adjacency(closed,multipliers);cols=["origin","destination","baseline","scenario","cost_change","status"]
            for s in origins:
                new=dijkstra(modified,s)[0]
                for t in destinations:
                    b,c=ds[s].get(t),new.get(t);status="unreachable_baseline" if b is None else "disconnected" if c is None else "reachable"
                    rows.append([s,t,b,c,c-b if b is not None and c is not None else None,status])
            base_count=sum(r[2] is not None for r in rows);lost=sum(r[-1]=="disconnected" for r in rows)
            metrics.update(closed_edges=sorted(closed),baseline_reachable_pairs=base_count,disconnected_pairs=lost,retained_fraction=(base_count-lost)/base_count if base_count else None)
            features=[edge_feature(e,closed=e.id in closed,multiplier=multipliers.get(e.id,1),color="#b94f46" if e.id in closed else "#468675") for e in g.edges]
            if any(r[2] is not None and r[3] is not None for r in rows):plot("Baseline versus scenario OD impedance","basic_scatter","baseline","scenario",values=(["baseline","scenario"],[[r[2],r[3]] for r in rows if r[2] is not None and r[3] is not None]))
        elif kind=="od_matrix":
            cols=["origin","destination","cost"]
            rows=[[s,t,ds[s].get(t)] for s in origins for t in destinations]
            metrics={"reachable_pairs":sum(r[-1] is not None for r in rows),"unreachable_pairs":sum(r[-1] is None for r in rows)}
            if metrics["reachable_pairs"]:
                costs=sorted(r[-1] for r in rows if r[-1] is not None);plot("OD cumulative cost distribution","basic_line" if len(costs)>1 else "basic_column","cost","fraction",values=(["cost","fraction"],[[z,(i+1)/len(costs)] for i,z in enumerate(costs)]))
        elif kind=="nearest_facility":
            cols=["origin","facility","cost"]
            for s in origins:
                candidates=[(ds[s][t],t) for t in destinations if t in ds[s]]
                cost,t=min(candidates) if candidates else (None,None)
                rows.append([s,t,cost]);features.append(node_feature(g,s,facility=t,cost=cost))
        else:
            require(set(body.supply)==set(destinations),"Provide explicit positive supply for every facility.")
            supply=body.supply
            if kind=="two_step_fca":
                require(set(body.demand)==set(origins),"Provide explicit positive demand for every origin.")
                ratios={}
                for t in destinations:
                    demand=sum(body.demand[s] for s in origins if ds[s].get(t,math.inf)<=body.threshold)
                    ratios[t]=supply[t]/demand if demand else 0.
                score={s:sum(ratios[t] for t in destinations if ds[s].get(t,math.inf)<=body.threshold) for s in origins}
                metrics["unserved_supply"]=sum(supply[t] for t in destinations if ratios[t]==0)
                metrics["allocated_supply"]=sum(body.demand[s]*score[s] for s in origins)
            else:score={s:sum(supply[t]*math.exp(-body.beta*ds[s][t]) for t in destinations if t in ds[s]) for s in origins}
            cols=["origin","accessibility"];rows=[[s,score[s]] for s in origins];features=[node_feature(g,s,accessibility=score[s]) for s in origins]
            plot("Origin accessibility","basic_column","origin","accessibility")
    # Display styling is separate from raw values and never changes numerical products.
    field={'harmonic_centrality':'score','betweenness':'score','gravity_access':'accessibility','two_step_fca':'accessibility','edge_criticality':'lost_fraction','hazard_exposure':'mean'}.get(kind)
    if field:
        values=[f['properties'][field] for f in features if f['properties'].get(field) is not None]
        if values:
            lo,hi=min(values),max(values)
            for f in features:
                p=f['properties'];value=p.get(field)
                if value is None:p['color']='#909090';continue
                t=(value-lo)/(hi-lo) if hi>lo else .5
                p['color']='#%02x%02x%02x'%(round(38+165*t),round(117-52*t),round(165-98*t))
                if f['geometry']['type']=='Point':p['display_radius']=4+5*t
                else:p['display_width']=2+4*t
            metrics['display_scale']={'field':field,'minimum':lo,'maximum':hi,'description':'Linear display scale only; raw attribute retained.'}
    receipt={"schema":"geofathom-network-science","operation":kind,"assumption":METHODS[kind][1],"network_sha256":hashlib.sha256(serialized.encode()).hexdigest(),"cost_field":body.cost_field,"cost_unit":body.cost_unit if body.cost_field!="length_m" else "m","nodes":n,"edges":len(g.edges),"directed_arcs":arcs,"parameters":body.model_dump(exclude={"network","raster"}),"metrics":metrics}
    return {"operation":kind,"columns":cols,"rows":rows,"csv":table_csv(cols,rows),"features":{"type":"FeatureCollection","features":features},"figures":figures,"receipt":receipt}
