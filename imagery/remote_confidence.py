"""Bounded temperature fitting and scale-invariant feature support diagnostics."""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from analysis.science_raster import require


def calibrated_probabilities(probabilities, temperature=1.):
    require(np.isfinite(temperature) and .05<=temperature<=20,'Invalid saved calibration temperature.')
    logits=np.log(np.clip(probabilities,1e-15,1))/temperature
    return np.exp(logits-logsumexp(logits,axis=1,keepdims=True))


def fit_temperature(probabilities,truth,classes):
    indices=np.searchsorted(classes,truth)
    def loss(log_t):
        logits=np.log(np.clip(probabilities,1e-15,1))/np.exp(log_t)
        return float(np.mean(logsumexp(logits,axis=1)-logits[np.arange(len(truth)),indices]))
    fit=minimize_scalar(loss,bounds=(np.log(.05),np.log(20)),method='bounded',options={'xatol':1e-10})
    require(fit.success,'Probability calibration optimization failed.')
    # Identity is a valid candidate; do not worsen calibration-set likelihood.
    return float(np.exp(fit.x)) if fit.fun<loss(0) else 1.


def probability_scores(probabilities,truth,classes):
    indices=np.searchsorted(classes,truth);confidence=probabilities.max(axis=1)
    correct=np.argmax(probabilities,axis=1)==indices;one=np.eye(len(classes))[indices]
    bins=np.minimum((confidence*10).astype(int),9);reliability=[]
    for i in range(10):
        m=bins==i
        if m.any():reliability.append([float(confidence[m].mean()),float(correct[m].mean()),int(m.sum())])
    return {'multiclass_brier':float(np.mean(np.sum((probabilities-one)**2,axis=1))),
        'log_loss':float(-np.mean(np.log(np.clip(probabilities[np.arange(len(truth)),indices],1e-15,1)))),
        'ece':sum(abs(p-o)*n for p,o,n in reliability)/len(truth),'reliability':reliability}


def feature_support(x):
    mean=x.mean(axis=0);scale=x.std(axis=0,ddof=1)
    # Constant channels keep a finite, unit-relative numerical floor.
    scale=np.maximum(scale,np.maximum(np.abs(mean),1)*1e-12)
    z=(x-mean)/scale;cov=np.atleast_2d(np.cov(z,rowvar=False))
    covariance=.95*cov+.05*np.eye(x.shape[1]);whiten=np.linalg.cholesky(covariance)
    distance=np.linalg.norm(np.linalg.solve(whiten,z.T),axis=0)
    return {'mean':mean.tolist(),'scale':scale.tolist(),'covariance':covariance.tolist(),
        'lower':np.quantile(x,.005,axis=0).tolist(),'upper':np.quantile(x,.995,axis=0).tolist(),
        'distance_p95':float(np.quantile(distance,.95)),
        'scope':'Standardized training support; descriptive distance and marginal bounds, not an OOD probability.'}


def support_distance(x,model):
    s=model.get('feature_support')
    if s:
        mean=np.asarray(s['mean']);scale=np.asarray(s['scale']);cov=np.asarray(s['covariance']);z=(x-mean)/scale
        require(mean.shape==scale.shape==(x.shape[1],) and np.all(scale>0) and np.isfinite(z).all(),'Invalid training support standardization.')
    else:
        mean=np.asarray(model['training_mean']);cov=np.asarray(model['training_covariance']);z=x-mean
    require(cov.shape==(x.shape[1],x.shape[1]),'Invalid training support covariance.')
    return np.linalg.norm(np.linalg.solve(np.linalg.cholesky(cov),z.T),axis=0)
