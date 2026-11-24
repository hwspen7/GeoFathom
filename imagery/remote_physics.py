"""Physical model uncertainty and explicit image registration."""
import numpy as np
from analysis.science_raster import require

def thermal_uncertainty(v,p):
    l,e,t,u,d=(v[k] for k in ('radiance','emissivity','transmittance','upwelling','downwelling'))
    b=(l-u-t*(1-e)*d)/(t*e)
    good=np.logical_and.reduce([np.isfinite(z) for z in v.values()])&(b>0)
    out=np.full(b.shape,np.nan)
    l,e,t,u,d,b=(q[good] for q in (l,e,t,u,d,b))
    jac=[1/(t*e),(d-(l-u)/t)/e**2,-(l-u)/(t*t*e),-1/(t*e),-(1-e)/e]
    names=('radiance','emissivity','transmittance','upwelling','downwelling')
    sensitivity=np.stack([j*v[k+'_sd'][good] for j,k in zip(jac,names)])
    correlation=np.eye(5)
    for i in range(5):
        for j in range(i+1,5):correlation[i,j]=correlation[j,i]=p.get('rho'+str(i)+str(j),0)
    require(np.linalg.eigvalsh(correlation)[0]>=-1e-10,'Thermal correlation matrix must be positive semidefinite.')
    bsd=np.sqrt(np.maximum(0,np.einsum('in,ij,jn->n',sensitivity,correlation,sensitivity)))
    k1,k2=p['k1'],p['k2'];grad=k2*k1/(b*(b+k1)*np.log1p(k1/b)**2)
    out[good]=grad*bsd
    return out,{'correlation_matrix':correlation.tolist(),'input_order':list(names),'model':'First-order uncertainty conditional on supplied pixel standard deviations and constant correlation matrix; structural model discrepancy omitted.'}

def angular_sar(v,p,mask_only=False):
    # Vollrath et al. (2020) angular volume-scattering correction.
    z=v['sigma0'];theta=np.deg2rad(v['incidence']);s=np.deg2rad(v['slope']);a=np.deg2rad(v['aspect'])
    phi=np.deg2rad(p['look_azimuth'])-a
    alpha=np.arctan(np.tan(s)*np.cos(phi))
    complete=np.isfinite(z)&np.isfinite(theta)&np.isfinite(s)&np.isfinite(a)
    geometric=complete&(theta>np.deg2rad(1))&(theta<np.deg2rad(89))&(s<np.deg2rad(89))
    margin=np.deg2rad(p['margin_deg'])
    layover=geometric&(alpha>=theta-margin);shadow=geometric&(alpha<=-(np.pi/2-theta)+margin)
    valid=geometric&~layover&~shadow
    out=np.full(z.shape,np.nan)
    if mask_only:out[complete]=valid[complete].astype(float)
    else:
        i=theta[valid];r=alpha[valid]
        factor=np.tan(np.pi/2-i)/np.tan(np.pi/2-i+r)
        out[valid]=z[valid]/np.cos(i)*factor
    return out,{'active_layover_cells':int(layover.sum()),'active_shadow_cells':int(shadow.sum()),
                'usable_cells':int(valid.sum()),'model':'Angular volume-scattering slope correction; sensor-facing azimuth clockwise from grid north. Not full area-based RTC; passive shadow/layover not reconstructed.'}

def register_translation(v,p):
    ref=v['reference'];candidate=v['candidate'];mask=v['calibration'];h,w=ref.shape;r=p['max_shift']
    require(min(h,w)>2*r+2 and h*w*(2*r+1)**2<=50_000_000,'Registration search exceeds bounded work or image size.')
    support=np.isfinite(ref)&(mask==1);n=int(support.sum());require(n>=64,'Provide at least 64 stable reference pixels.')
    def slices(d,n):
        return (slice(max(d,0),min(n+d,n)),slice(max(-d,0),min(n-d,n)))
    scores=[]
    for dy in range(-r,r+1):
        ry,cy=slices(dy,h)
        for dx in range(-r,r+1):
            rx,cx=slices(dx,w);a=ref[ry,rx];b=candidate[cy,cx];ok=support[ry,rx]&np.isfinite(b)
            k=int(ok.sum())
            if k<max(64,p['min_overlap']*n):continue
            a=a[ok];b=b[ok];aa=a-a.mean();bb=b-b.mean();den=np.linalg.norm(aa)*np.linalg.norm(bb)
            if den>0:scores.append((float(np.clip(aa@bb/den,-1,1)),dy,dx,k))
    require(len(scores)>=2,'Insufficient textured overlap for translation registration.')
    scores.sort(reverse=True);best,dy,dx,k=scores[0];runner=scores[1][0]
    require(best>=p['min_correlation'] and best-runner>=p['peak_margin'],'Ambiguous or weak registration correlation.')
    out=np.full(ref.shape,np.nan);ry,cy=slices(dy,h);rx,cx=slices(dx,w);out[ry,rx]=candidate[cy,cx]
    return out,{'row_shift':dy,'column_shift':dx,'correlation':best,'peak_margin':best-runner,'matched_calibration_cells':k,
                'at_search_boundary':bool(abs(dy)==r or abs(dx)==r),'interpretation':'Integer pixel translation only; no wrap, rotation, subpixel adjustment or independent control-point accuracy.'}
