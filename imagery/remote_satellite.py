"""Satellite observation inference and exact metric cell-support transfer."""
import numpy as np
from scipy.stats import f
from scipy.sparse import csr_matrix
from analysis.science_raster import require

SAR_GAMMA_IDS={"sar_gamma_change_p","sar_gamma_ratio_low","sar_gamma_ratio_high"}

def gamma_change(v,p,kind):
    """Independent Gamma multilook intensity ratio test and confidence limits.

    Under constant backscatter, independent sample intensities divided by
    their means follow Gamma(L,1/L). Their ratio is F(2L_after,2L_before).
    ENL must be supplied from suitable homogeneous calibration regions.
    """
    a,b=v["before"],v["after"]
    good=np.isfinite(a)&np.isfinite(b)&(a>0)&(b>0)
    log_ratio=np.full(a.shape,np.nan)
    log_ratio[good]=np.log(b[good])-np.log(a[good])
    d1=2*p["enl_after"];d2=2*p["enl_before"];alpha=1-p["confidence"]
    if kind=="sar_gamma_change_p":
        # The ratio may exceed representable range for extremely small inputs.
        with np.errstate(over="ignore",under="ignore"):
            ratio=np.exp(log_ratio)
        out=np.minimum(1.,2*np.minimum(f.cdf(ratio,d1,d2),f.sf(ratio,d1,d2)))
    else:
        # Report log-ratio confidence bounds in dB to preserve finite range.
        q=f.ppf(1-alpha/2 if kind=="sar_gamma_ratio_low" else alpha/2,d1,d2)
        out=(10/np.log(10))*(log_ratio-np.log(q))
    out[~good]=np.nan
    return out,{"paired_positive_cells":int(good.sum()),"degrees_of_freedom":[d1,d2],
        "confidence":p["confidence"],"assumptions":"independent Gamma multilook intensity, supplied ENL, comparable calibrated acquisitions; pointwise inference, no spatial or multiple-test adjustment"}

def _overlap(n,step,origin,m,target_step,target_origin):
    """Sparse exact lengths in source-local coordinates, sorted half-open cells."""
    rows=[];cols=[];weights=[]
    offset=target_origin-origin
    for j in range(m):
        lo=offset+j*target_step;hi=lo+target_step
        begin=max(0,int(np.floor(lo/step)));end=min(n,int(np.ceil(hi/step)))
        if end-begin>10000:raise ValueError("One target interval exceeds 10,000 source intervals.")
        for i in range(begin,end):
            length=min(hi,(i+1)*step)-max(lo,i*step)
            if length>0:
                rows.append(j);cols.append(i);weights.append(length)
        if len(rows)>2_000_000:raise ValueError("Axis overlap budget exceeded.")
    return csr_matrix((weights,(rows,cols)),shape=(m,n))

def area_overlap(source,target,p,kind):
    """Conservative piecewise-constant remapping in the same projected CRS."""
    require(source.crs==target.crs and source.is_meter and target.is_meter,
            "Exact support overlap requires the same projected metre CRS.")
    a,b=source.transform,target.transform
    require(a.b==a.d==b.b==b.d==0 and min(a.a,b.a,-a.e,-b.e)>0,
            "Exact overlap requires north-up rectangular grids.")
    h,w=source.values.shape;th,tw=target.values.shape
    x=_overlap(w,a.a,a.c,tw,b.a,b.c)
    y=_overlap(h,-a.e,-a.f,th,-b.e,-b.f)
    require(y.nnz*w+x.nnz*th<=40_000_000 and th*w<=8_000_000,
            "Area-overlap work budget exceeded; crop the scene.")
    z=source.values;valid=np.isfinite(z)
    def remap(q):
        return (x@(y@q).T).T
    support=remap(valid.astype(float))
    weighted=remap(np.where(valid,z,0.))
    cell=b.a*(-b.e)
    coverage=np.clip(support/cell,0,1)
    out=coverage if kind=="align_overlap_coverage" else np.divide(weighted,support,
        out=np.full((th,tw),np.nan),where=(support>0)&(coverage+1e-12>=p["minimum_coverage"]))
    mask=np.isfinite(target.values);out[~mask]=np.nan
    return out,{"target_cell_area_m2":cell,"observed_support_area_m2":float(support[mask].sum()),
        "observed_integral":float(weighted[mask].sum()),"minimum_coverage":p["minimum_coverage"],
        "low_coverage_cells":int((mask&(coverage+1e-12<p["minimum_coverage"])).sum()),
        "assumption":"piecewise constant intensive source values on native cells; exact rectangular intersection, not geodesic equal area or new independent observations"}
