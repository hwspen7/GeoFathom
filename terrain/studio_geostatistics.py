"""Geostatistical covariance fitting, local ordinary kriging and spatial Gaussian errors.

Distances are in projected metres. Variogram fits are descriptive weighted
least squares; the ordinary-kriging variance is conditional on the model.
"""
import numpy as np
from .studio_data import FigureInputError

def require(condition,message):
    if not condition:raise FigureInputError(message)

def structure(h,model,scale):
    r=np.asarray(h,dtype=float)/scale
    if model=='exponential':return -np.expm1(-r)
    if model=='gaussian':return -np.expm1(-r*r)
    if model=='spherical':return np.where(r<1,1.5*r-.5*r**3,1.)
    raise FigureInputError('Unknown covariance model.')

def semivariance(h,model,nugget,partial_sill,scale):
    h=np.asarray(h,dtype=float)
    return np.where(h>0,nugget+partial_sill*structure(h,model,scale),0.)

def fit_variogram(h,v,pairs,model):
    h,v,w=map(lambda x:np.asarray(x,dtype=float),(h,v,pairs))
    require(len(h)>=4 and len(np.unique(h))>=3 and np.all(h>0) and np.all(v>=0) and np.all(w>0),
            'At least four lag observations and three distinct positive lag distances are required.')
    require(np.max(v)>0,'Constant semivariance cannot identify a covariance model.')
    w=w/w.sum();best=None
    # Solve nonnegative nugget and partial sill exactly for each scale.
    # Evaluate both boundary optima and the unrestricted interior optimum.
    for scale in np.geomspace(h.min()/4,h.max()*4,160):
        s=structure(h,model,scale)
        x=np.column_stack((np.ones(len(h)),s))
        b=np.linalg.lstsq(x*np.sqrt(w[:,None]),v*np.sqrt(w),rcond=None)[0]
        candidates=[np.array([np.sum(w*v),0.]),np.array([0.,max(0,np.sum(w*v*s)/np.sum(w*s*s))])]
        if np.all(b>=0):candidates.append(b)
        for nugget,sill in candidates:
            error=float(np.sum(w*(v-nugget-sill*s)**2))
            if best is None or error<best[0]:best=(error,float(nugget),float(sill),float(scale))
    error,nugget,sill,scale=best
    return {'model':model,'nugget':nugget,'partial_sill':sill,'scale_m':scale,
            'weighted_rmse':float(np.sqrt(error)),
            'practical_range_m':scale*({'exponential':-np.log(.05),'gaussian':np.sqrt(-np.log(.05)),'spherical':1}[model])}

def ordinary_kriging(points,values,target,fit,neighbors=24):
    """Solve local ordinary kriging using a covariance matrix and sum-one weights."""
    points=np.asarray(points,float);values=np.asarray(values,float);target=np.asarray(target,float)
    require(points.ndim==2 and points.shape[1]==2 and len(values)==len(points) and len(points)>=3,
            'Kriging requires at least three distinct projected observations.')
    distance=np.linalg.norm(points-target,axis=1)
    k=min(neighbors,len(points));idx=np.argsort(distance,kind='stable')[:k]
    p=points[idx];y=values[idx];d=distance[idx]
    if d[0]==0:return float(y[0]),0.
    require(len(np.unique(p,axis=0))==len(p),'Duplicate sample coordinates must be aggregated first.')
    h=np.linalg.norm(p[:,None,:]-p[None,:,:],axis=2)
    sill=fit['nugget']+fit['partial_sill']
    require(sill>0,'Kriging requires a positive covariance sill.')
    gamma=lambda z:semivariance(z,fit['model'],fit['nugget'],fit['partial_sill'],fit['scale_m'])
    cov=(sill-gamma(h))/sill;c=(sill-gamma(d))/sill
    a=np.ones((k+1,k+1));a[:k,:k]=cov;a[k,k]=0
    try:sol=np.linalg.solve(a,np.r_[c,1.])
    except np.linalg.LinAlgError as exc:raise FigureInputError('Singular kriging system; change covariance model or sample layout.') from exc
    weights=sol[:k]
    var=sill*(1-weights@c-sol[-1])
    require(np.isfinite(var) and var>=-1e-7*sill,'Invalid kriging variance.')
    return float(weights@y),float(max(0,var))

def leave_one_out(points,values,fit,neighbors):
    require(4<=len(values)<=500,'Kriging leave-one-out supports 4–500 observed cells.')
    prediction=[];variance=[]
    for i,p in enumerate(points):
        keep=np.arange(len(values))!=i
        pred,var=ordinary_kriging(points[keep],values[keep],p,fit,neighbors)
        prediction.append(pred);variance.append(var)
    return np.asarray(prediction),np.asarray(variance)

def gaussian_kernel(length,pixel):
    require(length>0 and pixel>0,'Correlation length and pixel spacing must be positive.')
    # Convolution of white noise with this kernel yields approximately
    # exp(-h²/(2*length²)); discrete normalization preserves variance.
    sigma=length/(np.sqrt(2)*pixel);radius=max(1,int(np.ceil(4*sigma)))
    require(radius<=512,'Correlation length exceeds the bounded convolution radius.')
    x=np.arange(-radius,radius+1);k=np.exp(-.5*(x/sigma)**2)
    return k/np.linalg.norm(k)

def correlated_noise(rng,shape,dx,dy,length,sigma):
    ky=gaussian_kernel(length,dy);kx=gaussian_kernel(length,dx)
    h,w=shape;ph=h+len(ky)-1;pw=w+len(kx)-1
    require(ph*pw<=4_000_000,'Padded correlated field exceeds memory budget.')
    white=rng.normal(size=(ph,pw))
    # Linear convolution via FFT with zero padding. Retain the valid interior,
    # where every cell has the same full kernel support and variance.
    fy=ph+len(ky)-1;fx=pw+len(kx)-1
    require(fy*fx<=8_000_000,'FFT correlation workspace exceeds memory budget.')
    transformed=np.fft.rfft2(white,s=(fy,fx))
    transformed*=np.fft.fft(ky,n=fy)[:,None]
    transformed*=np.fft.rfft(kx,n=fx)[None,:]
    full=np.fft.irfft2(transformed,s=(fy,fx))
    return sigma*full[len(ky)-1:len(ky)-1+h,len(kx)-1:len(kx)-1+w].copy()
