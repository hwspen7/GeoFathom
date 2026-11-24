"""Global spectral covariance methods and finite-library Bayesian retrieval."""
import numpy as np
from scipy.special import logsumexp
from analysis.science_raster import require

def spectral_covariance(stack,wavelength,kind,p):
    wl=np.asarray(wavelength,float);n,h,w=stack.shape
    require(len(wl)==n and np.isfinite(wl).all() and np.all(wl>0) and np.all(np.diff(wl)>0),'Ordered positive wavelengths required.')
    valid=np.isfinite(stack).all(axis=0);x=stack[:,valid].T
    require( max(30,2*n)<=len(x)<=100000 and len(x)*n*n<=60_000_000,'Spectral covariance population or work budget exceeded.')
    mean=x.mean(axis=0);center=x-mean;cov=center.T@center/(len(x)-1)
    def regularize(c):
        scale=float(np.trace(c)/n);require(scale>1e-15,'Spectral covariance has insufficient variation.')
        return (1-p['shrinkage'])*c+p['shrinkage']*scale*np.eye(n)
    out=np.full((h,w),np.nan)
    if kind=='spectral_rx':
        chol=np.linalg.cholesky(regularize(cov));z=np.linalg.solve(chol,center.T)
        out[valid]=np.sum(z*z,axis=0)
        return out,[],[],{'population':len(x),'mean':mean.tolist(),'shrinkage':p['shrinkage'],'interpretation':'Global regularized Reed-Xiaoli distance; not calibrated anomaly probability.'}
    # Adjacent differences estimate noise covariance under locally constant signal,
    # with one half correcting the variance of two independent observations.
    pairs=[]
    for a,b in ((stack[:,:,1:],stack[:,:,:-1]),(stack[:,1:,:],stack[:,:-1,:])):
        ok=np.isfinite(a).all(axis=0)&np.isfinite(b).all(axis=0)
        pairs.append((a[:,ok]-b[:,ok]).T)
    d=np.concatenate(pairs,axis=0)
    require(len(d)>=max(30,2*n) and len(d)*n*n<=120_000_000,'Insufficient or excessive adjacent noise pairs.')
    noise=regularize(np.cov(d,rowvar=False)/2)
    from scipy.linalg import eigh
    values,vectors=eigh(cov,noise);order=np.argsort(values)[::-1];values=values[order];vectors=vectors[:,order]
    j=p['component']-1;require(j<n,'MNF component exceeds band count.')
    # Deterministic sign convention, except within degenerate eigenspaces.
    vector=vectors[:,j];vector=vector*(1 if vector[np.argmax(abs(vector))]>=0 else -1)
    out[valid]=center@vector
    return out,['component','variance_ratio'],[[i+1,float(a)] for i,a in enumerate(values)],{
        'noise_pairs':len(d),'noise_covariance':noise.tolist(),'component':j+1,'loading':vector.tolist(),
        'interpretation':'Noise-whitened generalized eigenanalysis; spatial differences assume locally constant signal and independent noise. Eigenvectors in tied eigenspaces are nonunique.'}

def matched_filter(v,p):
    stack=np.stack([v[k] for k in ('blue','green','red','nir')]);mask=v['calibration']
    valid=np.isfinite(stack).all(axis=0);x=stack[:,valid].T
    background=valid&(mask==1);target=valid&(mask==2)
    require(background.sum()>=20 and target.sum()>=3 and len(x)<=500000,'Use at least 20 background and 3 target spectra within work budget.')
    b=stack[:,background].T;mu=b.mean(axis=0);t=stack[:,target].mean(axis=1)-mu
    cov=np.cov(b,rowvar=False);scale=float(np.trace(cov)/4)
    require(scale>1e-15,'Background covariance is degenerate.')
    cov=(1-p['shrinkage'])*cov+p['shrinkage']*scale*np.eye(4)
    weight=np.linalg.solve(cov,t);den=float(t@weight)
    require(den>1e-10,'Target spectrum is not distinct from background.')
    out=np.full(valid.shape,np.nan);out[valid]=(x-mu)@weight/den
    return out,{'target_cells':int(target.sum()),'background_cells':int(background.sum()),'weight':(weight/den).tolist(),'interpretation':'Linear matched-filter response: background mean zero and target mean one by construction; not a calibrated abundance or probability.'}

def library_retrieval(v,rows,p,kind):
    # Rows are parameter, prior mass, blue, green, red, NIR; supplied externally.
    table=np.asarray(rows,dtype=float)
    require(table.ndim==2 and table.shape[1]==6 and 2<=len(table)<=2048 and np.isfinite(table).all(),'Library requires 2–2048 finite rows of parameter, prior, blue, green, red, NIR.')
    parameter,prior=table[:,0],table[:,1];spectra=table[:,2:]
    require(np.all((parameter>=0)&(parameter<=20)) and np.all(prior>0) and np.all((spectra>=0)&(spectra<=1)),'Library LAI, positive prior masses and reflectance must be physically valid.')
    require(np.unique(parameter).size>=2,'Library requires at least two distinct LAI values.')
    stack=np.stack([v[k] for k in ('blue','green','red','nir')]);valid=np.isfinite(stack).all(axis=0)
    x=stack[:,valid].T;require(len(x)>0 and len(x)*len(table)<=20_000_000,'Library inversion work budget exceeded.')
    sd=np.array([p[k+'_sd'] for k in ('blue','green','red','nir')]);logprior=np.log(prior);logprior-=logsumexp(logprior)
    out=np.full(valid.shape,np.nan);result=np.full(len(x),np.nan);excluded=0
    for i in range(0,len(x),512):
        z=x[i:i+512];chi=np.sum(((z[:,None,:]-spectra[None,:,:])/sd)**2,axis=2)
        score=-chi/2+logprior;weights=np.exp(score-logsumexp(score,axis=1,keepdims=True))
        mean=weights@parameter
        if kind=='lai_library_mean':value=mean
        elif kind=='lai_library_sd':value=np.sqrt(np.sum(weights*(parameter[None,:]-mean[:,None])**2,axis=1))
        else:value=np.min(chi,axis=1)
        if kind!='lai_library_misfit':
            bad=np.min(chi,axis=1)>p['max_chi2'];value[bad]=np.nan;excluded+=int(bad.sum())
        result[i:i+len(z)]=value
    out[valid]=result
    return out,{'library_rows':len(table),'rejected_out_of_library_cells':excluded,'observation_sd':sd.tolist(),
        'interpretation':'Discrete Bayesian retrieval conditional on supplied simulated or measured spectral library and prior masses; independent Gaussian band errors. Not a built-in PROSAIL simulator, nor an unconditional confidence interval.'}
