"""Irregular-time local linear state-space model and conditional randomization."""
import numpy as np
from analysis.science_raster import require

def kalman(stack,t,p,kind):
    n,h,w=stack.shape;require(n*h*w<=1_000_000,'State-space work budget exceeded.')
    q=p['process_variance'];r=p['observation_variance'];horizon=p['horizon']
    flat=stack.reshape(n,-1);count=np.isfinite(flat).sum(axis=0);out=np.full(h*w,np.nan)
    # Continuous-time integrated Brownian velocity: process variance is
    # acceleration spectral density in value^2 / time^3.
    def advance(m,c,dt):
        F=np.array([[1.,dt],[0.,1.]])
        Q=q*np.array([[dt**3/3,dt**2/2],[dt**2/2,dt]])
        return F@m,F@c@F.T+Q
    sq=np.zeros(n);norm=np.zeros(n);num=np.zeros(n,int);baseline=np.zeros(n)
    for j in np.flatnonzero(count>=p['minimum_observations']):
        y=flat[:,j];ids=np.flatnonzero(np.isfinite(y));first=ids[0]
        m=np.array([y[first],0.]);c=np.diag([r,p['initial_velocity_variance']]);last=y[first];seen=1;errors=[];base=[]
        for i in range(first+1,n):
            m,c=advance(m,c,float(t[i]-t[i-1]))
            if not np.isfinite(y[i]):continue
            e=y[i]-m[0];s=c[0,0]+r
            require(np.isfinite(s) and s>0,'State-space covariance overflow; rescale time and variance.')
            if seen>=p['minimum_observations']:
                errors.append(e*e);base.append((y[i]-last)**2);sq[i]+=e*e;norm[i]+=e*e/s;num[i]+=1;baseline[i]+=(y[i]-last)**2
            gain=c[:,0]/s;m=m+gain*e
            # Joseph form preserves positive semidefiniteness under roundoff.
            A=np.eye(2)-np.outer(gain,[1.,0.]);c=A@c@A.T+r*np.outer(gain,gain);c=(c+c.T)/2
            last=y[i];seen+=1
        if kind=='kalman_level':out[j]=m[0]
        elif kind=='kalman_velocity':out[j]=m[1]
        elif kind in ('kalman_forecast','kalman_forecast_sd'):
            m,c=advance(m,c,horizon);out[j]=m[0] if kind=='kalman_forecast' else np.sqrt(max(0.,c[0,0]+r))
        elif len(errors)>=2:
            out[j]=np.sqrt(np.mean(errors)) if kind=='kalman_hindcast_rmse' else (1-sum(errors)/sum(base) if sum(base)>0 else np.nan)
    rows=[[float(t[i]),int(num[i]),float(np.sqrt(sq[i]/num[i])),float(np.sqrt(baseline[i]/num[i])),float(norm[i]/num[i])] for i in np.flatnonzero(num)]
    return out.reshape(h,w),['time','pairs','model_rmse','persistence_rmse','mean_normalized_innovation_squared'],rows,{
        'model':'Continuous-time local linear trend with integrated Brownian velocity, fixed supplied process and measurement variances, first-observation initialization, Joseph covariance update. Missing dates propagate state without measurement. No fitted hyperparameters.',
        'forecast_time':float(t[-1]+horizon),'validation':'Prequential one-step-ahead predictions use only earlier data; variance is conditional on supplied Gaussian model. Select hyperparameters on separate training data, not the reported test errors.'}

def permutation_lag(stack,p):
    """Global lagged rook association; shuffle earlier date spatial labels only."""
    n,h,w=stack.shape;B=p['permutations'];require(n*h*w*(B+1)<=30_000_000,'Permutation work budget exceeded.')
    rng=np.random.default_rng(p['seed']);rows=[]
    for i in range(1,n):
        old=stack[i-1];new=stack[i];a=np.isfinite(old);b=np.isfinite(new)
        if a.sum()<4 or b.sum()<4:continue
        os=old[a].std();ns=new[b].std()
        if os==0 or ns==0:continue
        x=(old[a]-old[a].mean())/os;y=np.zeros((h,w));y[b]=(new[b]-new[b].mean())/ns
        # Each eligible directed previous-neighbor/current pair receives
        # equal weight; fixed mask and graph across randomizations.
        weights=np.zeros((h,w));degree=np.zeros((h,w),int)
        for src,dst in ((np.s_[:-1,:],np.s_[1:,:]),(np.s_[1:,:],np.s_[:-1,:]),(np.s_[:,:-1],np.s_[:,1:]),(np.s_[:,1:],np.s_[:,:-1])):
            weights[src]+=y[dst];degree[src]+=b[dst]
        pairs=int(degree[a].sum())
        if pairs==0:continue
        wgt=weights[a]/pairs;obs=float(x@wgt)
        null=np.array([rng.permutation(x)@wgt for _ in range(B)])
        # Conditional randomization under spatial exchangeability at the
        # earlier date. Two-sided absolute statistic, including observed draw.
        prob=(1+np.count_nonzero(abs(null)>=abs(obs)-1e-14))/(B+1)
        rows.append([i+1,pairs,obs,float(prob),float(null.mean()),float(null.std(ddof=1))])
    require(rows,'No valid lagged spatial pairs.')
    # BY adjusts across date comparisons with overlapping observations.
    x=np.array([r[3] for r in rows]);m=len(x);order=np.argsort(x);rank=np.arange(1,m+1)
    q=np.empty(m);q[order]=np.clip(np.minimum.accumulate((x[order]*m*np.sum(1/rank)/rank)[::-1])[::-1],0,1)
    for r,v in zip(rows,q):r.append(float(v))
    return ['acquisition','pairs','association','p_value','null_mean','null_sd','by_q'],rows,{
        'permutations':B,'seed':p['seed'],'interpretation':'Randomization null: earlier-date valid spatial values are exchangeable over fixed valid cells conditional on current field. Existing spatial autocorrelation violates this null; do not interpret as a test of independence between autocorrelated fields. BY assumes valid marginal p-values.'}
