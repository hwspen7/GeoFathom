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


def register_subpixel(v,p):
    from scipy.ndimage import map_coordinates
    from scipy.optimize import minimize
    _,meta=register_translation(v,p)
    ref=v['reference'];candidate=v['candidate'];h,w=ref.shape;dy=meta['row_shift'];dx=meta['column_shift']
    require(not meta['at_search_boundary'],'Integer peak at search boundary; increase search radius.')
    row,col=np.nonzero(np.isfinite(ref)&(v['calibration']==1))
    yy=row-dy;xx=col-dx
    ok=(yy>=1)&(yy<h-1)&(xx>=1)&(xx<w-1);row,col,yy,xx=(a[ok] for a in (row,col,yy,xx))
    for i in (-1,0,1):
        for j in (-1,0,1):
            ok=np.isfinite(candidate[yy+i,xx+j]);row,col,yy,xx=(a[ok] for a in (row,col,yy,xx))
    require(len(row)>=64,'Insufficient fixed complete support for subpixel refinement.')
    a=ref[row,col];a=a-a.mean();norm=np.linalg.norm(a);require(norm>0,'Reference support must vary.')
    def objective(shift):
        b=map_coordinates(candidate,[row-shift[0],col-shift[1]],order=1,mode='constant',cval=np.nan,prefilter=False)
        if not np.isfinite(b).all():return 2.
        b=b-b.mean();den=norm*np.linalg.norm(b)
        return 1-float(np.clip(a@b/den,-1,1)) if den>0 else 2.
    fit=minimize(objective,[dy,dx],method='Powell',bounds=[(dy-.9,dy+.9),(dx-.9,dx+.9)],options={'xtol':1e-6,'ftol':1e-10,'maxiter':80})
    require(fit.success and np.isfinite(fit.fun) and fit.fun<=objective([dy,dx])+1e-10,'Subpixel refinement failed.')
    rr,cc=np.indices(ref.shape,dtype=float);out=map_coordinates(candidate,[rr-fit.x[0],cc-fit.x[1]],order=1,mode='constant',cval=np.nan,prefilter=False)
    hold=np.isfinite(ref)&np.isfinite(out)&(v['calibration']==2)
    meta.update(subpixel_row_shift=float(fit.x[0]),subpixel_column_shift=float(fit.x[1]),refined_correlation=float(1-fit.fun),
                fixed_support_cells=len(row),heldout_cells=int(hold.sum()),
                heldout_rmse=float(np.sqrt(np.mean((out[hold]-ref[hold])**2))) if hold.any() else None,
                interpretation='Bilinear subpixel translation refinement; mask 2 evaluates radiometric residuals only; not independent geometric control-point accuracy.')
    return out,meta
