"""Local space-time hotspot scores with trajectory-permutation maxT inference."""
import numpy as np
from scipy.sparse import csr_matrix
from analysis.science_raster import require

def hotspot(stack,t,p,kind):
    n,h,w=stack.shape;radius=p['radius'];B=p['permutations'];alpha=p['alpha']
    require(np.allclose(np.diff(t),np.diff(t)[0],rtol=1e-7,atol=1e-10),'Hotspot persistence requires regular acquisitions.')
    valid=np.isfinite(stack).all(axis=0);r,c=np.where(valid);m=len(r)
    require(12<=m<=2500,'Hotspots require 12–2,500 complete cells.')
    require(radius<=10,'Hotspot neighborhood radius limited to ten cells.')
    offsets=[(a,b) for a in range(-radius,radius+1) for b in range(-radius,radius+1) if abs(a)+abs(b)<=radius]
    lookup={(a,b):i for i,(a,b) in enumerate(zip(r,c))}
    neighbors=[]
    for i,(a,b) in enumerate(zip(r,c)):
        neighbors.extend((i,lookup[(a+dr,b+dc)]) for dr,dc in offsets if (a+dr,b+dc) in lookup)
    ii,jj=np.asarray(neighbors).T;A=csr_matrix((np.ones(len(ii)),(ii,jj)),shape=(m,m));k=np.asarray(A.sum(axis=1)).ravel()
    eligible=(k>=2)&(k<m);require(eligible.any(),'Local neighborhoods must include 2 to m-1 cells.')
    require(n*A.nnz*(B+1)<=50_000_000,'Hotspot permutation budget exceeded.')
    x=stack[:,valid];sd=x.std(axis=1)
    require(np.all(sd>0),'All dates need spatial variance for hotspot inference.')
    z=(x-x.mean(axis=1,keepdims=True))/sd[:,None]
    norm=np.sqrt(np.maximum((m*k-k*k)/(m-1),1e-30))
    def score(x):return (A@x.T).T/norm
    obs=score(z);rng=np.random.default_rng(p['seed']);extreme=np.zeros_like(obs,dtype=int);maxima=[]
    for _ in range(B):
        null=score(z[:,rng.permutation(m)]);mx=float(np.max(abs(null[:,eligible])));maxima.append(mx)
        extreme+=mx>=abs(obs)-1e-12
    prob=(1+extreme)/(B+1);hot=(prob<=alpha)&(obs>0)&eligible;cold=(prob<=alpha)&(obs<0)&eligible
    hot_count=hot.sum(axis=0);cold_count=cold.sum(axis=0)
    if kind=='hotspot_latest_z':v=obs[-1]
    elif kind=='hotspot_latest_p':v=prob[-1]
    elif kind=='hotspot_hot_fraction':v=hot_count/n
    elif kind=='hotspot_cold_fraction':v=cold_count/n
    else:
        v=np.zeros(m);v[hot_count>0]=3;v[cold_count>0]=6
        v[(hot_count==1)&hot[-1]]=2;v[(cold_count==1)&cold[-1]]=5
        v[hot_count/n>=.8]=1;v[cold_count/n>=.8]=4;v[(hot_count>0)&(cold_count>0)]=7
    out=np.full((h,w),np.nan);out[r[eligible],c[eligible]]=v[eligible]
    rows=[[i+1,int(hot[i].sum()),int(cold[i].sum()),int(eligible.sum())] for i in range(n)]
    return out,['acquisition','hot_cells','cold_cells','tested_cells'],rows,{'permutations':B,'seed':p['seed'],'alpha':alpha,'tested_cells':int(eligible.sum()),'null_maximum_quantiles':[[float(q),float(np.quantile(maxima,q))] for q in np.linspace(0,1,21)],
      'interpretation':'Local Gi* standardized scores; max statistic over all cells and dates under shared trajectory permutation. Global-null family-wise error control requires spatially exchangeable complete trajectories; spatial autocorrelation violates this null. Not ArcGIS Emerging Hot Spot.',
      'class_codes':{'0':'none','1':'persistent hot','2':'new hot','3':'intermittent hot','4':'persistent cold','5':'new cold','6':'intermittent cold','7':'mixed signs'}}
