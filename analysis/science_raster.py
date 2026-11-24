"""Numerically stable raster operators, design-based sampling and spatial statistics."""
import numpy as np
from terrain.studio_data import FigureInputError, pareto_mask
from rasterio.transform import Affine

def require(ok,msg):
    if not ok:raise FigureInputError(msg)

def focal(z,r,kind):
    h,w=z.shape
    require(z.size*(2*r+1)**2<=60_000_000,'Neighborhood exceeds cell-window work budget.')
    count=np.zeros(z.shape,np.int32);mean=np.zeros(z.shape);m2=np.zeros(z.shape)
    low=np.full(z.shape,np.inf);high=np.full(z.shape,-np.inf)
    pad=np.pad(z,r,constant_values=np.nan)
    for dy in range(2*r+1):
        for dx in range(2*r+1):
            v=pad[dy:dy+h,dx:dx+w];ok=np.isfinite(v)
            count[ok]+=1
            delta=v[ok]-mean[ok];mean[ok]+=delta/count[ok];m2[ok]+=delta*(v[ok]-mean[ok])
            low[ok]=np.minimum(low[ok],v[ok]);high[ok]=np.maximum(high[ok],v[ok])
    out={'focal_mean':mean,'focal_sd':np.sqrt(np.maximum(0,m2)/np.maximum(count,1)),
         'focal_min':low,'focal_max':high,'focal_range':high-low}[kind]
    out[~np.isfinite(z)]=np.nan
    return out

def sample_cells(z,method,count,seed):
    rng=np.random.default_rng(seed);valid=np.flatnonzero(np.isfinite(z));n=len(valid)
    require(count<=n,'Requested sample exceeds valid cell population.')
    if method=='sample_random':
        idx=np.sort(rng.choice(valid,count,replace=False));weight=np.full(count,n/count)
    elif method=='sample_systematic':
        idx=valid[np.floor((np.arange(count)+rng.random())*n/count).astype(int)];weight=np.full(count,n/count)
    elif method=='sample_stratified':
        values=z.flat[valid];classes,labels,sizes=np.unique(values,return_inverse=True,return_counts=True)
        require(len(classes)<=128 and count>=len(classes),'Stratified sampling needs 1–128 classes and at least one sample per class.')
        allocation=np.ones(len(classes),int)
        for _ in range(count-len(classes)):
            j=int(np.argmax(np.where(allocation<sizes,1/allocation,-1)));allocation[j]+=1
        pairs=[(rng.choice(valid[labels==j],a,replace=False),np.full(a,sizes[j]/a)) for j,a in enumerate(allocation)]
        idx=np.concatenate([p[0] for p in pairs]);weight=np.concatenate([p[1] for p in pairs])
    else:
        def partition(ids,k):
            if k==1:return [(rng.choice(ids),len(ids))]
            row,col=np.unravel_index(ids,z.shape);order=np.argsort(row if np.ptp(row)>=np.ptp(col) else col,kind='stable')
            left=k//2;cut=max(left,min(len(ids)-(k-left),round(len(ids)*left/k)))
            return partition(ids[order[:cut]],left)+partition(ids[order[cut:]],k-left)
        pairs=partition(valid,count);idx,weight=map(np.asarray,zip(*pairs));idx=idx.astype(int)
    return idx,weight

def adjacency(z,neighborhood='rook'):
    valid=np.isfinite(z);lookup=np.full(z.shape,-1,dtype=np.int64);lookup[valid]=np.arange(valid.sum())
    a=[];b=[]
    pairs=[(lookup[:,:-1],lookup[:,1:]),(lookup[:-1,:],lookup[1:,:])]
    if neighborhood=='queen':pairs.extend([(lookup[:-1,:-1],lookup[1:,1:]),(lookup[:-1,1:],lookup[1:,:-1])])
    for first,second in pairs:
        mask=(first>=0)&(second>=0);a.append(first[mask]);b.append(second[mask])
    return z[valid],np.concatenate(a),np.concatenate(b)

def permutation_stat(z,kind,permutations,seed,neighborhood='rook',return_null=False):
    values,a,b=adjacency(z,neighborhood);n=len(values);edges=len(a)
    require(n>=3 and edges>0,'Spatial statistics require at least three valid observations and neighboring pairs.')
    require(edges*(permutations+1)<=30_000_000,'Permutation edge budget exceeded.')
    if kind=='join_count':
        require(np.isin(values,[0,1]).all(),'Join counts require binary 0/1 values.')
        def stat(v):return float(np.count_nonzero(v[a]!=v[b]))
        expected=2*np.sum(values==0)*np.sum(values==1)/(n*(n-1))*edges
    else:
        values=values-values.mean();ss=values@values;require(ss>0,'Spatial statistic undefined for constant population.')
        if kind=='global_moran':
            def stat(v):return float(n*np.sum(v[a]*v[b])/(edges*ss))
            expected=-1/(n-1)
        else:
            def stat(v):return float((n-1)*np.sum((v[a]-v[b])**2)/(2*edges*ss))
            expected=1.
    observed=stat(values);rng=np.random.default_rng(seed)
    null=np.array([stat(rng.permutation(values)) for _ in range(permutations)])
    p=(1+np.count_nonzero(np.abs(null-expected)>=abs(observed-expected)-1e-14))/(permutations+1)
    meta={'observed':observed,'expected':float(expected),'p_two_sided':float(p),'null_mean':float(null.mean()),
            'null_sd':float(null.std(ddof=1)),'valid_cells':n,'undirected_edges':edges,'permutations':permutations,'neighborhood':neighborhood,'minimum_p':1/(permutations+1)}
    return (meta,null) if return_null else meta

def decision(stack,common,kind,weights,directions,pairwise):
    k=len(stack);x=stack[:,common].T;meta={}
    require(len(directions)==k and all(d in ('benefit','cost') for d in directions),'Provide one benefit/cost direction per criterion.')
    if kind=='pareto_cells':
        out=pareto_mask(x[:,0],x[:,1],directions[0]=='benefit',directions[1]=='benefit').astype(float)
    else:
        if kind=='ahp_overlay':
            a=np.asarray(pairwise,float);require(a.shape==(k,k) and np.all(np.isfinite(a)) and np.all(a>0),'AHP requires a positive square pairwise matrix.')
            require(np.allclose(np.diag(a),1,rtol=0,atol=1e-8) and np.allclose(a*a.T,1,rtol=1e-6,atol=1e-8),'AHP matrix must be reciprocal with diagonal ones.')
            eig,vec=np.linalg.eig(a);j=np.argmax(eig.real);w=np.abs(vec[:,j].real);w/=w.sum()
            ri=[0,0,.58,.90,1.12,1.24,1.32,1.41][k-1];cr=max(0,float((eig[j].real-k)/(k-1)/ri)) if ri else 0.
            require(cr<=.10+1e-10,'AHP consistency ratio exceeds 0.10. Revise pairwise judgments.')
            meta['consistency_ratio']=cr
        else:
            w=np.asarray(weights,float);require(w.shape==(k,) and np.all(np.isfinite(w)) and np.all(w>0),'Provide one positive weight per criterion.')
            w=w/w.sum()
        meta['normalized_weights']=w.tolist()
        if kind=='topsis':
            norms=np.linalg.norm(x,axis=0);require(np.all(norms>0),'TOPSIS requires nonzero criterion norms.')
            v=x/norms*w;benefit=np.array(directions)=='benefit';best=np.where(benefit,v.max(axis=0),v.min(axis=0));worst=np.where(benefit,v.min(axis=0),v.max(axis=0))
            good=np.linalg.norm(v-best,axis=1);bad=np.linalg.norm(v-worst,axis=1)
            out=np.divide(bad,good+bad,out=np.full(len(x),.5),where=good+bad>0)
        else:
            span=np.ptp(x,axis=0);v=np.divide(x-x.min(axis=0),span,out=np.full_like(x,.5),where=span>0)
            v[:,np.array(directions)=='cost']=1-v[:,np.array(directions)=='cost'];out=v@w
    result=np.full(common.shape,np.nan);result[common]=out
    return result,meta

def raster_operation(kind,stack,common,grid,params):
    z=stack[0];unit=grid.unit;transform=grid.transform
    if kind.startswith('focal_'):out=focal(z,params['radius'],kind)
    elif kind.startswith('aggregate_'):
        f=params['factor'];h,w=z.shape;require(h%f==0 and w%f==0,'Grid dimensions must be divisible by the aggregation factor.')
        a=z.reshape(h//f,f,w//f,f);count=np.isfinite(a).sum(axis=(1,3));out=np.nansum(a,axis=(1,3))
        if kind=='aggregate_mean':out=np.divide(out,count,out=np.full_like(out,np.nan),where=count>0)
        else:out[count==0]=np.nan
        transform=transform*Affine.scale(f,f)
    elif kind=='raster_threshold':out=np.where(np.isfinite(z),(z>=params['threshold']).astype(float),np.nan);unit='class'
    elif kind=='raster_ratio':out=np.divide(z,stack[1],out=np.full_like(z,np.nan),where=common&(stack[1]!=0));unit='unitless'
    else:
        require(bool(unit),'Declare known compatible physical units for multiraster arithmetic.')
        with np.errstate(invalid='ignore'):
            out={'raster_sum':lambda:stack.sum(axis=0),'raster_difference':lambda:z-stack[1],
                 'raster_mean':lambda:stack.mean(axis=0),'raster_sd':lambda:stack.std(axis=0),
                 'raster_min':lambda:stack.min(axis=0),'raster_max':lambda:stack.max(axis=0)}[kind]()
        out[~common]=np.nan
    return out,transform,unit


def local_stat(z,kind,view,permutations,seed,alpha):
    from terrain.studio_inference import conditional_moran,adjust_by
    values,a,b=adjacency(z);n=len(values);valid=np.isfinite(z)
    require(n>=5 and len(a)>0,'Local spatial analysis requires at least five cells and spatial adjacency.')
    centered=values-values.mean();sd=float(np.sqrt(np.mean(centered**2)))
    require(sd>0,'Local statistics undefined for a constant population.')
    standardized=centered/sd
    source=np.r_[a,b];target=np.r_[b,a];degree=np.bincount(source,minlength=n)
    eligible=degree>0
    lag=np.divide(np.bincount(source,weights=standardized[target],minlength=n),degree,
                  out=np.full(n,np.nan),where=eligible)
    def to_grid(v):
        out=np.full(z.shape,np.nan);out[valid]=v;return out
    if kind=='local_moran':
        statistic=standardized*lag
        if view=='statistic':return to_grid(statistic),{'tested_cells':int(eligible.sum())},'unitless'
        p,q=conditional_moran(to_grid(standardized),to_grid(lag),np.where(valid,to_grid(degree),0),permutations,seed)
        pv=p[valid];qv=q[valid]
    else:
        # Gi* weights are binary rook neighbors plus focal cell, and
        # denominator uses the finite population variance.
        count=degree+1;denom=np.sqrt(count*(n-count)/(n-1))
        eligible=eligible&(denom>0)
        require(eligible.any(),'No nondegenerate Gi* neighborhoods.')
        def gi(v):
            sums=v+np.bincount(source,weights=v[target],minlength=n)
            return np.divide(sums,denom,out=np.full(n,np.nan),where=eligible)
        statistic=gi(standardized)
        if view=='statistic':return to_grid(statistic),{'tested_cells':int(eligible.sum())},'unitless'
        require((len(source)+n)*(permutations+1)<=30_000_000,'Gi* permutation work budget exceeded.')
        rng=np.random.default_rng(seed);extreme=np.zeros(n,np.int32)
        for _ in range(permutations):
            simulated=gi(rng.permutation(standardized))
            extreme[eligible]+=np.abs(simulated[eligible])>=np.abs(statistic[eligible])-1e-12
        pv=np.full(n,np.nan);qv=np.full(n,np.nan)
        pv[eligible]=(1+extreme[eligible])/(permutations+1);qv[eligible]=adjust_by(pv[eligible])
    significant=np.isfinite(qv)&(qv<=alpha)
    if view=='p':out=pv;unit='probability'
    elif view=='q':out=qv;unit='probability'
    else:
        out=np.where(np.isfinite(qv),0.,np.nan);unit='class'
        if kind=='local_moran':
            out[significant&(standardized>0)&(lag>0)]=1
            out[significant&(standardized<0)&(lag<0)]=2
            out[significant&(standardized>0)&(lag<0)]=3
            out[significant&(standardized<0)&(lag>0)]=4
        else:
            out[significant&(statistic>0)]=1;out[significant&(statistic<0)]=2
    return to_grid(out),{'tested_cells':int(np.isfinite(qv).sum()),'significant_cells':int(significant.sum()),'minimum_p':1/(permutations+1),
                        'correction':'Benjamini–Yekutieli','best_case_minimum_q_bound':min(1.,float(np.sum(1/np.arange(1,int(np.isfinite(qv).sum())+1)))/(permutations+1)),'cluster_codes':{'0':'not significant','1':'high-high or hotspot','2':'low-low or coldspot',**({'3':'high-low','4':'low-high'} if kind=='local_moran' else {})}},unit
