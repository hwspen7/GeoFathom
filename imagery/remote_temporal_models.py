"""Explicit seasonal and multiple-change models."""
import numpy as np
from analysis.science_raster import require

def seasonal_metrics(stack,times,p,kind):
    t=np.asarray(times,float);n,h,w=stack.shape
    period=p['period'];require(len(t)==n and 6<=n<=64 and np.isfinite(t).all() and np.all(np.diff(t)>0),'Ordered finite acquisition times required.')
    require(t[-1]-t[0]>=period and n*h*w<=2_000_000,'Seasonal analysis requires a full period and bounded workspace.')
    t=t-t[0];phase=2*np.pi*t/period
    design=np.column_stack((np.ones(n),t/t[-1],np.cos(phase),np.sin(phase)))
    flat=stack.reshape(n,-1);patterns,ids=np.unique(np.packbits(np.isfinite(flat).T,axis=1),axis=0,return_inverse=True)
    require(len(patterns)<=4096,'Too many missingness patterns.')
    out=np.full(h*w,np.nan)
    for j,pattern in enumerate(patterns):
        mask=np.unpackbits(pattern)[:n].astype(bool);x=design[mask]
        if mask.sum()<6 or np.linalg.matrix_rank(x)<4 or np.linalg.cond(x)>1e8:continue
        pos=np.flatnonzero(ids==j);coef=np.linalg.lstsq(x,flat[np.ix_(mask,pos)],rcond=None)[0]
        amplitude=np.hypot(coef[2],coef[3]);ok=amplitude>=p['min_amplitude'];pos=pos[ok]
        peak=np.mod(np.arctan2(coef[3,ok],coef[2,ok]),2*np.pi)*period/(2*np.pi)
        half=period*np.arccos(2*p['season_fraction']-1)/(2*np.pi)
        if kind=='season_peak':out[pos]=peak
        elif kind=='season_start':out[pos]=np.mod(peak-half,period)
        elif kind=='season_end':out[pos]=np.mod(peak+half,period)
        else:out[pos]=2*half
    return out.reshape(h,w),{'period':period,'phase_origin':float(times[0]),'threshold_fraction_of_seasonal_range':p['season_fraction'],
        'minimum_amplitude':p['min_amplitude'],'model':'Detrended first harmonic; start/end modulo period, duration at supplied relative amplitude threshold. Not observed phenology dates.'}

def segmented_means(stack,times,p,kind):
    t=np.asarray(times,float);n,h,w=stack.shape;m=p['min_segment'];pen=p['penalty']
    require(len(t)==n and np.isfinite(t).all() and np.all(np.diff(t)>0),'Ordered finite acquisition times required.')
    require(n>=2*m and n*n*h*w<=5_000_000,'Segmented mean fit exceeds bounded work or lacks observations.')
    out=np.full((h,w),np.nan)
    for r,c in np.ndindex(h,w):
        ok=np.isfinite(stack[:,r,c]);y=stack[ok,r,c];tt=t[ok];size=len(y)
        if size<2*m:continue
        y=y-y.mean();cs=np.r_[0.,np.cumsum(y)];ss=np.r_[0.,np.cumsum(y*y)]
        cost=np.full(size+1,np.inf);previous=np.full(size+1,-1,int);cost[0]=-pen
        for end in range(m,size+1):
            starts=np.arange(end-m+1);starts=starts[np.isfinite(cost[starts])]
            if not len(starts):continue
            sse=np.maximum(0,ss[end]-ss[starts]-(cs[end]-cs[starts])**2/(end-starts))
            score=cost[starts]+sse+pen;i=int(np.argmin(score));cost[end]=score[i];previous[end]=starts[i]
        ends=[];end=size
        while previous[end]>0:end=int(previous[end]);ends.append(end)
        if kind=='segmented_count':out[r,c]=len(ends)
        elif ends:
            q=ends[-1];out[r,c]=tt[q-1]+(tt[q]-tt[q-1])/2
    return out,{'penalty':pen,'min_segment':m,'model':'Exact dynamic programming minimizing within-segment SSE plus penalty per breakpoint. Missing observations omitted; split time midpoint between retained observations; not significance or causal evidence.'}
