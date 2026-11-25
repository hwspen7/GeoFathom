"""Conditional atmospheric LUT interpolation and dual-pol complex-Wishart change."""
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.stats import chi2
from analysis.science_raster import require

WISHART_IDS={"sar_wishart_statistic","sar_wishart_p"}

def atmospheric_lut(toa,aod,water,lut,minimum_denominator=.01):
    """Interpolate externally generated band atmospheric coefficients.

    LUT axes: aerosol optical depth at a declared reference wavelength and
    total column water in declared units. Geometry, profile, ozone and band
    response are fixed by the LUT generator. This routine never retrieves
    aerosol or extrapolates outside the supplied physical model.
    """
    a=np.asarray(lut["aod"],float);w=np.asarray(lut["water"],float)
    require(a.ndim==w.ndim==1 and 2<=len(a)<=256 and 2<=len(w)<=256 and np.isfinite(a).all() and np.isfinite(w).all()
        and a[0]>=0 and w[0]>=0 and np.all(np.diff(a)>0) and np.all(np.diff(w)>0),"Invalid increasing nonnegative atmospheric LUT axes.")
    names=("path","transmission","spherical_albedo")
    values=[np.asarray(lut[n],float) for n in names]
    require(all(z.shape==(len(a),len(w)) and np.isfinite(z).all() and np.all((z>=0)&(z<=1)) for z in values)
        and np.all(values[1]>0),"Invalid physical LUT coefficient grids.")
    require(isinstance(lut.get("model"),str) and bool(lut["model"].strip()) and isinstance(lut.get("water_unit"),str)
        and bool(lut["water_unit"].strip()) and isinstance(lut.get("aod_wavelength_nm"),(int,float))
        and np.isfinite(lut["aod_wavelength_nm"]) and lut["aod_wavelength_nm"]>0,"Declare LUT model, water unit and AOD reference wavelength.")
    toa,aod,water=map(lambda z:np.asarray(z,float),(toa,aod,water))
    require(toa.shape==aod.shape==water.shape and toa.size<=2_000_000 and .000001<=minimum_denominator<=1,"Invalid atmospheric LUT input or budget.")
    support=np.isfinite(toa)&np.isfinite(aod)&np.isfinite(water)&(aod>=a[0])&(aod<=a[-1])&(water>=w[0])&(water<=w[-1])
    out=np.full(toa.shape,np.nan)
    if support.any():
        coeff=RegularGridInterpolator((a,w),np.stack(values,axis=-1),bounds_error=True)(np.column_stack((aod[support],water[support])))
        y=toa[support]-coeff[:,0];den=coeff[:,1]+coeff[:,2]*y
        z=np.divide(y,den,out=np.full(y.shape,np.nan),where=den>=minimum_denominator)
        z[(z<-.2)|(z>1.6)]=np.nan;out[support]=z
    return out,{"lut_supported_cells":int(support.sum()),"valid_cells":int(np.isfinite(out).sum()),
        "outside_lut_or_missing_cells":int(toa.size-support.sum()),"model":lut["model"],
        "water_unit":lut["water_unit"],"aod_wavelength_nm":lut["aod_wavelength_nm"],
        "assumption":"supplied band-specific external LUT at fixed observation geometry and atmosphere profile; no extrapolation or retrieval"}

def _logdet(a,b,r,i):
    scale=np.maximum(np.maximum(a,b),np.hypot(r,i))
    safe=np.where(scale>0,scale,np.nan)
    aa,bb,rr,ii=[q/safe for q in (a,b,r,i)]
    det=aa*bb-rr*rr-ii*ii
    good=np.isfinite(det)&(aa>0)&(bb>0)&(det>1e-12)
    return np.where(good,2*np.log(safe)+np.log(np.where(good,det,1.)),np.nan)

def wishart_change(v,p,kind):
    """Two independent complex-Wishart sample covariance likelihood ratio.

    Two-dimensional complex Hermitian covariance has four real parameters;
    the chi-square approximation has four degrees of freedom and may be
    inaccurate for small effective looks or non-Wishart distributions.
    """
    first=[v[f"{r}_before"] for r in ("c11","c22","c12_real","c12_imag")]
    second=[v[f"{r}_after"] for r in ("c11","c22","c12_real","c12_imag")]
    l1,l2=p["looks_before"],p["looks_after"];weight=l1/(l1+l2)
    pooled=[weight*x+(1-weight)*y for x,y in zip(first,second)]
    log1,log2,logpool=map(lambda q:_logdet(*q),(first,second,pooled))
    # Remove small negative floating residuals when the covariances coincide.
    stat=np.maximum(0.,2*((l1+l2)*logpool-l1*log1-l2*log2))
    out=chi2.sf(stat,4) if kind=="sar_wishart_p" else stat
    return out,{"supported_positive_definite_cells":int(np.isfinite(stat).sum()),"degrees_of_freedom":4,
        "looks_before":l1,"looks_after":l2,
        "assumption":"independent dual-pol complex Wishart covariance estimates, supplied effective looks, asymptotic chi-square; no multiplicity correction"}
