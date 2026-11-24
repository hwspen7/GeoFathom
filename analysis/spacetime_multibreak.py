"""Exact finite-segment dynamic programming for seasonal structural breaks."""
import numpy as np
from analysis.science_raster import require

def multi_break(stack,t,p,kind):
    n,h,w=stack.shape;minimum=p['min_segment'];period=p['period'];K=p['max_breaks']+1
    require(minimum>=6 and n>=minimum*2 and n*n*h*w<=1_000_000,'Multi-break harmonic work budget or minimum support exceeded.')
    tt=(t-t[0])/(t[-1]-t[0]);phase=2*np.pi*(t-t[0])/period
    X=np.column_stack((np.ones(n),tt,np.cos(phase),np.sin(phase)))
    out=np.full((h,w),np.nan);hist=np.zeros(K,int);breaks=[]
    for i,j in np.ndindex(h,w):
        y=stack[:,i,j];ok=np.isfinite(y);v=y[ok];time=t[ok];a=X[ok];m=len(v)
        if m<minimum or time[-1]-time[0]<period:continue
        scale=float(v.std())
        if not scale>0:continue
        v=(v-v.mean())/scale;cost=np.full((m+1,m+1),np.inf)
        for s in range(m-minimum+1):
            for e in range(s+minimum,m+1):
                if time[e-1]-time[s]<period:continue
                H=a[s:e]
                if np.linalg.matrix_rank(H)<4 or np.linalg.cond(H)>1e8:continue
                z=v[s:e];b=np.linalg.lstsq(H,z,rcond=None)[0];cost[s,e]=np.sum((z-H@b)**2)
        dp=np.full((K+1,m+1),np.inf);prev=np.full((K+1,m+1),-1,int);dp[0,0]=0
        for k in range(1,K+1):
            for e in range(k*minimum,m+1):
                vals=dp[k-1,:e]+cost[:e,e];s=int(np.argmin(vals));dp[k,e]=vals[s];prev[k,e]=s
        if not np.isfinite(dp[1,m]):continue
        k=np.arange(1,K+1)
        bic=m*np.log(np.maximum(dp[1:,m],1e-24)/m)+(5*k-1)*np.log(m)+(k-1)*p['bic_threshold']
        best=int(np.argmin(bic))+1;hist[best-1]+=1
        cuts=[];e=m
        for q in range(best,1,-1):
            s=prev[q,e];cuts.append(float((time[s-1]+time[s])/2));e=s
        cuts.reverse();breaks.extend(cuts)
        if kind=='multi_harmonic_count':out[i,j]=best-1
        elif kind=='multi_harmonic_bic':out[i,j]=bic[0]-bic[best-1]
        elif cuts:out[i,j]=cuts[0] if kind=='multi_harmonic_first' else cuts[-1]
    rows=[[i,int(v)] for i,v in enumerate(hist)]
    return out,['break_count','cells'],rows,{'interpretation':'Exact DP minimum SSE for each feasible segment count, followed by BIC plus explicit extra break penalty. Each independent harmonic segment spans at least a full cycle and six observations. Offline model selection; not CCDC or BFAST online monitoring, not a p-value.','break_histogram':rows}
