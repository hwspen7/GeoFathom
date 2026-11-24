"""Explicitly coregistered complex SAR products; no raw mission focusing."""
import numpy as np
from analysis.science_raster import require

def complex_products(v,p,kind):
    from scipy.ndimage import uniform_filter
    a=v['master_real']+1j*v['master_imag'];b=v['slave_real']+1j*v['slave_imag']
    good=np.isfinite(a)&np.isfinite(b)
    if kind=='insar_wrapped_phase':
        valid=good&(abs(a)>0)&(abs(b)>0);out=np.full(good.shape,np.nan)
        out[valid]=np.angle(a[valid]*np.conj(b[valid]))
        return out,{'valid_cells':int(valid.sum()),'phase_convention':'master times conjugate slave; radians; no flat earth or topography removal'}
    r=p['radius'];width=2*r+1
    require(a.size*width**2<=180_000_000,'Coherence neighborhood work budget exceeded.')
    z=np.where(good,a,0);w=np.where(good,b,0)
    count=uniform_filter(good.astype(float),size=width,mode='constant')*width**2
    cross=z*np.conj(w)
    c=uniform_filter(cross.real,size=width,mode='constant')+1j*uniform_filter(cross.imag,size=width,mode='constant')
    den=np.sqrt(np.maximum(0,uniform_filter(abs(z)**2,size=width,mode='constant')*uniform_filter(abs(w)**2,size=width,mode='constant')))
    ok=good&(count>=p['min_samples']-1e-8)&(den>0)
    out=np.full(good.shape,np.nan);out[ok]=np.clip(abs(c[ok])/den[ok],0,1)
    return out,{'radius':r,'minimum_common_samples':p['min_samples'],'valid_cells':int(ok.sum()),'model':'Sample complex coherence on common valid support; no debiasing or coregistration validation.'}

def calibrated_power(v):
    # Explicit linear amplitude gain supplied from mission LUT, already interpolated.
    amplitude=v['amplitude'];gain=v['gain'];noise=v['noise']
    raw=amplitude**2*gain**2-noise
    valid=np.isfinite(raw)&(raw>=0);out=np.where(valid,raw,np.nan)
    return out,{'negative_noise_corrected_cells':int((np.isfinite(raw)&(raw<0)).sum()),
                'model':'Power = amplitude² times gain² minus calibrated noise power. Supplied LUT convention; not automated mission metadata calibration.'}

def cloud_candidates(v,p):
    b,g,r,n,s=(v[k] for k in ('blue','green','red','nir','swir1'))
    valid=np.logical_and.reduce([np.isfinite(x) for x in (b,g,r,n,s)])
    mean=(b+g+r)/3;white=np.divide(abs(b-mean)+abs(g-mean)+abs(r-mean),3*mean,out=np.full(mean.shape,np.inf),where=mean>0)
    cloud=valid&(mean>=p['visible_min'])&(white<=p['whiteness_max'])&(s>=p['swir_min'])
    # This intentionally conservative spectral test is not a learned cloud mask.
    return np.where(valid,cloud.astype(float),np.nan),{'candidate_cloud_cells':int(cloud.sum()),
        'interpretation':'Bright spectrally neutral visible and SWIR candidate mask. Snow, bright surfaces and thin cloud can be misclassified; needs reference validation.'}
