"""Seasonally adjusted structural changes and observation-supported extremes."""
import numpy as np
from analysis.science_raster import require

def harmonic_break(stack,t,p,kind):
    n,h,w=stack.shape;m=p['min_segment'];period=p['period']
    require(m>=6 and n>=2*m and n*n*h*w<=4_000_000,'Seasonal break search needs two segments of six or more observations and bounded work.')
    require(t[-1]-t[0]>=2*period,'Need at least two full seasonal periods.')
    tt=(t-t[0])/(t[-1]-t[0]);phase=2*np.pi*(t-t[0])/period
    X=np.column_stack((np.ones(n),tt,np.cos(phase),np.sin(phase)))
    out=np.full((h,w),np.nan);selected=0;eligible=0;times=[];improvements=[]
    for i,j in np.ndindex(h,w):
        mask=np.isfinite(stack[:,i,j]);x=X[mask];y=stack[mask,i,j];time=t[mask];k=len(y)
        if k<2*m:continue
        scale=float(np.std(y))
        if not scale>0:continue
        y=(y-y.mean())/scale
        if np.linalg.matrix_rank(x)<4 or np.linalg.cond(x)>1e8:continue
        base=np.linalg.lstsq(x,y,rcond=None)[0];sse0=float(np.sum((y-x@base)**2))
        best=None
        for q in range(m,k-m+1):
            if time[q-1]-time[0]<period or time[-1]-time[q]<period:continue
            a=x[:q];b=x[q:]
            if np.linalg.matrix_rank(a)<4 or np.linalg.matrix_rank(b)<4 or max(np.linalg.cond(a),np.linalg.cond(b))>1e8:continue
            c=np.linalg.lstsq(a,y[:q],rcond=None)[0];d=np.linalg.lstsq(b,y[q:],rcond=None)[0]
            sse=float(np.sum((y[:q]-a@c)**2)+np.sum((y[q:]-b@d)**2))
            if best is None or sse<best[0]:best=(sse,q,c,d)
        if best is None:continue
        eligible+=1;sse,q,c,d=best
        # Include the discrete breakpoint in the complexity penalty; BIC is
        # a model-selection diagnostic, not a calibrated change p-value.
        gain=k*np.log(max(sse0,1e-24)/max(sse,1e-24))-5*np.log(k)
        changed=gain>p['bic_threshold'];when=(time[q]+time[q-1])/2
        if changed:selected+=1;times.append(float(when));improvements.append(float(gain))
        boundary=np.array([1.,(when-t[0])/(t[-1]-t[0]),0.,0.])
        if kind=='harmonic_break_bic':out[i,j]=gain
        elif kind=='harmonic_break_flag':out[i,j]=float(changed)
        elif changed:
            if kind=='harmonic_break_time':out[i,j]=when
            elif kind=='harmonic_break_level':out[i,j]=scale*(d-c)@boundary
            else:out[i,j]=scale*(np.hypot(d[2],d[3])-np.hypot(c[2],c[3]))
    return out,{'eligible_cells':eligible,'selected_break_cells':selected,'selected_break_times':times[:1000],
        'selected_bic_improvements':improvements[:1000],'interpretation':'Exhaustive single structural break in intercept, slope and first harmonic; each segment spans at least one full period. BIC improvement includes five extra parameters including breakpoint. Level change excludes seasonal component; no significance or causal attribution. Not BFAST, CCDC or LandTrendr.'}

def events(stack,t,p,kind):
    n,h,w=stack.shape;out=np.full((h,w),np.nan);threshold=p['threshold'];gap=p['maximum_gap']
    minimum=p['minimum_observations'];runs=[];counts=np.zeros(n,int);support=np.zeros(n,int)
    for i,j in np.ndindex(h,w):
        y=stack[:,i,j];valid=np.isfinite(y)
        if valid.sum()<minimum:continue
        active=valid&(y>threshold);count=0;longest=0.;duration=0.;area=0.;start=None
        for q in range(n):
            if not active[q]:start=None;continue
            support[q]+=1
            if start is None or q==0 or t[q]-t[q-1]>gap:
                start=q;count+=1;counts[q]+=1
            else:
                dt=t[q]-t[q-1];duration+=dt
                area+=dt*((y[q]-threshold)+(y[q-1]-threshold))/2
                longest=max(longest,t[q]-t[start])
        out[i,j]={'event_count':count,'event_longest_span':longest,'event_total_span':duration,'event_integrated_excess':area}[kind]
    rows=[[float(t[i]),int(counts[i]),int(support[i])] for i in range(n)]
    return out,['time','event_starts','active_cells'],rows,{'threshold':threshold,'maximum_gap':gap,
        'interpretation':'Runs of consecutive observed exceedances, split by missing/nonexceedance dates or excessive time gap. Spans count only intervals between adjacent above-threshold acquisitions; integrated excess uses trapezoids on those intervals. Not continuous event duration or a formal lower bound without interpolation assumptions.'}
