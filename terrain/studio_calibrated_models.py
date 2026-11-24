"""Bounded domain models with explicit calibration and held-out validation.

All training is deterministic and uses only declared training observations.
No prediction is called validated unless it is evaluated on withheld data.
"""
import numpy as np
from .studio_data import FigureInputError

def require(ok,message):
    if not ok:raise FigureInputError(message)

def simplex_project(v):
    """Euclidean projection onto nonnegative rows with unit sum."""
    u=np.sort(v,axis=-1)[...,::-1];cs=np.cumsum(u,axis=-1)-1
    j=np.arange(1,v.shape[-1]+1);rho=np.sum(u>cs/j,axis=-1)-1
    theta=np.take_along_axis(cs,rho[...,None],axis=-1)/(rho[...,None]+1)
    return np.maximum(v-theta,0)

def spectral_unmix(observations,endmembers):
    """Fully constrained least squares using projected accelerated gradient."""
    y=np.asarray(observations,float);e=np.asarray(endmembers,float)
    require(y.ndim==2 and e.ndim==2 and y.shape[1]==e.shape[1] and 2<=len(e)<=8,
            'Unmixing requires 2–8 supplied endmember spectra with matching band counts.')
    require(np.all(np.isfinite(y)) and np.all(np.isfinite(e)) and np.all((y>=0)&(y<=1)) and np.all((e>=0)&(e<=1)),
            'Unmixing requires finite calibrated reflectance in [0,1].')
    require(np.linalg.matrix_rank(e[1:]-e[0])==len(e)-1,'Endmembers are affinely dependent; fractions are not identifiable.')
    require(y.shape[0]*len(e)<=4_000_000,'Unmixing exceeds bounded abundance workspace.')
    gram=e@e.T;L=np.linalg.norm(gram,2)
    require(L>0,'Degenerate endmembers.')
    target=y@e.T
    x=np.full((len(y),len(e)),1/len(e));z=x.copy();t=1.
    for i in range(600):
        new=simplex_project(z-(z@gram-target)/L)
        step=np.max(np.abs(new-x));tnew=(1+np.sqrt(1+4*t*t))/2
        z=new+(t-1)/tnew*(new-x);x=new;t=tnew
        if step<1e-8:
            residual=np.max(np.abs(x-simplex_project(x-(x@gram-target)/L)))
            if residual<1e-7:break
    kkt=float(np.max(np.abs(x-simplex_project(x-(x@gram-target)/L))))
    require(kkt<1e-6,'Abundance optimizer did not meet the projected-gradient convergence tolerance.')
    rmse=np.sqrt(np.mean((x@e-y)**2,axis=1))
    return x,rmse,{'iterations':i+1,'projected_gradient_residual':kkt,'endmember_condition':float(np.linalg.cond(e[1:]-e[0]))}

def linear_reservoir(rain,recession,runoff_factor,initial=0.):
    """One-step conservative discrete reservoir; rain and flow are depth per step."""
    rain=np.asarray(rain,float)
    require(np.all(np.isfinite(rain)) and np.all(rain>=0) and 0<=recession<1 and 0<=runoff_factor<=1 and initial>=0,
            'Nonnegative rainfall/storage and physical reservoir coefficients required.')
    q=np.empty(len(rain));storage=np.empty(len(rain));s=initial
    for i,p in enumerate(rain):
        available=s+runoff_factor*p
        q[i]=(1-recession)*available;s=recession*available;storage[i]=s
    return q,storage

def flow_metrics(observed,predicted):
    e=predicted-observed;var=np.sum((observed-observed.mean())**2)
    return {'rmse':float(np.sqrt(np.mean(e*e))),'mae':float(np.mean(np.abs(e))),
            'bias':float(e.mean()),'nse':float(1-np.sum(e*e)/var) if var>0 else None,
            'volume_bias_pct':float(100*np.sum(e)/observed.sum()) if observed.sum()>0 else None}

def calibrate_reservoir(rain,flow,train_fraction):
    """Chronological split; fit only training depth series, carry storage forward."""
    rain,flow=np.asarray(rain,float),np.asarray(flow,float)
    require(len(rain)==len(flow) and 20<=len(rain)<=20000 and np.all(np.isfinite(flow)) and np.all(flow>=0),
            'Calibration needs 20–20,000 nonnegative flow-depth observations.')
    n=int(len(rain)*train_fraction);require(n>=10 and len(rain)-n>=5,'Need at least ten training and five validation steps.')
    require(np.sum(rain[:n])>0 and np.ptp(flow[:n])>0,'Training period needs rain and varying observed flow.')
    # For a given recession coefficient, optimal bounded runoff coefficient
    # follows by linear least squares. Search deterministic coarse and local grids.
    best=None
    def evaluate(k):
        nonlocal best
        q,_=linear_reservoir(rain[:n],k,1)
        denom=q@q
        if denom<=0:return
        c=float(np.clip(q@flow[:n]/denom,0,1));error=float(np.mean((q*c-flow[:n])**2))
        if best is None or error<best[0]:best=(error,float(k),c)
    for k in np.linspace(0,.999,81):evaluate(k)
    center=best[1]
    for k in np.linspace(max(0,center-.013),min(.9999,center+.013),81):evaluate(k)
    _,k,c=best;q,s=linear_reservoir(rain,k,c)
    return q,s,{'recession':k,'runoff_factor':c,'training_count':n,'validation_count':len(rain)-n,
                'training':flow_metrics(flow[:n],q[:n]),'validation':flow_metrics(flow[n:],q[n:]),
                'mass_balance_error':float(c*rain.sum()-q.sum()-s[-1])}

def block_regression(coords,features,target,block_size,folds,alpha):
    """Spatially grouped held-out ridge regression; fold-local standardization."""
    coords,features,target=map(lambda v:np.asarray(v,float),(coords,features,target))
    n=len(target);require(12<=n<=20000 and features.ndim==2 and 1<=features.shape[1]<=12 and coords.shape==(n,2),
                         'Spatial validation requires 12–20,000 projected observations and 1–12 features.')
    require(np.all(np.isfinite(coords)) and np.all(np.isfinite(features)) and np.all(np.isfinite(target)) and block_size>0 and alpha>=0,
            'Complete finite coordinates and features, positive block size and nonnegative ridge penalty required.')
    blocks=np.floor((coords-coords.min(axis=0))/block_size)
    require(np.max(blocks)<1e12,'Block grid is too fine for coordinate extent.')
    unique,ids,counts=np.unique(blocks,axis=0,return_inverse=True,return_counts=True)
    require(3<=folds<=10 and len(unique)>=folds,'At least one distinct spatial block per fold required.')
    # Greedy balanced partition of complete blocks; no block straddles folds.
    assignment=np.zeros(len(unique),dtype=int);loads=np.zeros(folds,int)
    for j in np.argsort(-counts,kind='stable'):
        k=int(np.argmin(loads));assignment[j]=k;loads[k]+=counts[j]
    fold=assignment[ids];pred=np.full(n,np.nan);metrics=[]
    for k in range(folds):
        test=fold==k;train=~test
        require(int(train.sum())>features.shape[1]+1,'Insufficient training observations for selected features.')
        x=features[train];mean=x.mean(axis=0);std=x.std(axis=0);std[std==0]=1
        design=(x-mean)/std;y=target[train];center=y.mean()
        if alpha==0:coef=np.linalg.lstsq(design,y-center,rcond=None)[0]
        else:coef=np.linalg.solve(design.T@design+alpha*np.eye(x.shape[1]),design.T@(y-center))
        pred[test]=center+(features[test]-mean)/std@coef
        metrics.append({'fold':k+1,'training_count':int(train.sum()),'validation_count':int(test.sum()),
                        'validation_blocks':int((assignment==k).sum()),**flow_metrics(target[test],pred[test])})
    return pred,fold+1,{'block_size_m':block_size,'blocks':len(unique),'folds':metrics,'overall':flow_metrics(target,pred),
                        'ridge_penalty':alpha,'warning':'Entire spatial blocks are held out. Adjacent blocks may still be spatially correlated; no buffer or external-site validation is implied.'}

def voxel_counts(x,y,z,size):
    """Sparse occupied voxel counts with explicit origin and half-open bins."""
    points=np.column_stack((x,y,z));require(np.all(np.isfinite(points)) and size>0,'Finite coordinates and positive voxel size required.')
    origin=points.min(axis=0);scaled=(points-origin)/size
    require(np.max(scaled)<1e12,'Voxel grid too fine for point extent.')
    cells=np.floor(scaled).astype(np.int64)
    idx,counts=np.unique(cells,axis=0,return_counts=True)
    center=origin+(idx+.5)*size
    return center,counts,origin
