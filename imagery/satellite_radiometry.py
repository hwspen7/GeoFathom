"""Conditional shortwave radiative-transfer uncertainty and spectral response."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from analysis.science_raster import require

ATMOS_IDS={"atmospheric_reflectance_sd","atmospheric_reflectance_condition"}

def atmospheric_error(v,p,kind):
    """Lambertian inversion Jacobian for TOA, path, transmission and albedo.

    Supplied correlated coefficient uncertainty; excludes atmospheric model
    discrepancy and retrieval uncertainty not included in the inputs.
    """
    y=v["toa"]-v["path"];t=v["transmission"];s=v["spherical_albedo"]
    den=t+s*y
    good=np.logical_and.reduce([np.isfinite(z) for z in v.values()])&(den>=p["min_denominator"])
    rho=np.divide(y,den,out=np.full(y.shape,np.nan),where=good)
    good &= (rho>=-.2)&(rho<=1.6)
    y,t,den=y[good],t[good],den[good]
    jac=np.stack((t,-t,-y,-y*y))/den**2
    out=np.full(rho.shape,np.nan)
    if kind=="atmospheric_reflectance_condition":
        out[good]=np.linalg.norm(jac,axis=0)
        corr=None
    else:
        names=("toa","path","transmission","spherical_albedo")
        corr=np.eye(4)
        for i in range(4):
            for j in range(i+1,4):
                corr[i,j]=corr[j,i]=p["rho"+str(i)+str(j)]
        require(np.linalg.eigvalsh(corr)[0]>=-1e-10,"Atmospheric error correlation matrix must be positive semidefinite.")
        sensitivity=jac*np.stack([v[k+"_sd"][good] for k in names])
        out[good]=np.sqrt(np.maximum(0,np.einsum("in,ij,jn->n",sensitivity,corr,sensitivity)))
    return out,{"valid_cells":int(good.sum()),"minimum_denominator":p["min_denominator"],
        "correlation_matrix":corr.tolist() if corr is not None else None,
        "assumption":"local first-order Lambertian inversion; externally supplied coefficients; no structural model uncertainty"}

def spectral_response(wavelength,spectra,response_wavelength,response,solar=None):
    """Exact integration of piecewise-linear spectrum, SRF and solar irradiance.

    Two-point Gauss-Legendre quadrature integrates their cubic product on
    each union-knot interval. No extrapolation of nonzero response is allowed.
    Solar irradiance weighting is optional, on the input spectrum grid.
    """
    x=np.asarray(wavelength,float);q=np.asarray(response_wavelength,float)
    y=np.asarray(spectra,float);r=np.asarray(response,float)
    require(x.ndim==q.ndim==1 and 2<=len(x)<=20000 and 2<=len(q)<=20000,"Use 2–20,000 wavelength knots per grid.")
    require(np.isfinite(x).all() and np.isfinite(q).all() and x[0]>0 and q[0]>0 and np.all(np.diff(x)>0) and np.all(np.diff(q)>0),"Wavelengths must increase strictly in the same positive units.")
    require(y.ndim in (1,2) and y.shape[-1]==len(x) and y.size<=2_000_000 and np.isfinite(y).all(),"Invalid bounded spectra.")
    require(r.shape==q.shape and np.isfinite(r).all() and np.all(r>=0) and r.max()>0,"Nonnegative, nonzero spectral response required.")
    # Include the intervals adjacent to nonzero response knots.
    positive=np.flatnonzero(r>0)
    lo=q[max(0,positive[0]-1)];hi=q[min(len(q)-1,positive[-1]+1)]
    require(x[0]<=lo and x[-1]>=hi,"Spectrum does not span the full nonzero response support.")
    knots=np.unique(np.r_[lo,hi,x[(x>lo)&(x<hi)],q[(q>lo)&(q<hi)]])
    mid=(knots[1:]+knots[:-1])/2;half=np.diff(knots)/2
    nodes=np.ravel(np.column_stack((mid-half/np.sqrt(3),mid+half/np.sqrt(3))))
    weights=np.repeat(half,2)*np.interp(nodes,q,r,left=0,right=0)
    if solar is not None:
        sun=np.asarray(solar,float)
        require(sun.shape==x.shape and np.isfinite(sun).all() and np.all(sun>=0),"Solar irradiance must be nonnegative on the spectrum grid.")
        weights*=np.interp(nodes,x,sun)
    norm=float(weights.sum())
    require(norm>0 and np.isfinite(norm),"Integrated response is zero or invalid.")
    z=np.atleast_2d(y)
    require(len(z)*len(nodes)<=40_000_000,"Spectral convolution work budget exceeded.")
    bands=np.array([np.dot(np.interp(nodes,x,row),weights)/norm for row in z])
    require(np.isfinite(bands).all(),"Spectral convolution overflow.")
    return {"band_values":bands.tolist(),"effective_wavelength":float(nodes@weights/norm),
        "response_integral":norm,"solar_weighted":solar is not None,"support":[float(lo),float(hi)],
        "assumption":"piecewise-linear input spectra, relative spectral response and optional solar irradiance; not a full cross-sensor BRDF or atmospheric correction"}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path);args=parser.parse_args()
    raw=args.config.read_bytes()
    result=spectral_response(**json.loads(raw));result["input_sha256"]=hashlib.sha256(raw).hexdigest()
    print(json.dumps(result,indent=2,allow_nan=False))

if __name__=="__main__":main()
