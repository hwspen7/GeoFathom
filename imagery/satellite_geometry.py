"""Robust local affine satellite georeferencing and independent checkpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from pyproj import CRS
from analysis.science_raster import require

def fit_affine(controls,checkpoints,epsg,*,huber_m=2.,iterations=80,tolerance=1e-10):
    """Fit pixel-center coordinates to projected XY with Huber IRLS.

    Controls and independent checkpoints are explicitly disjoint. This is
    local affine georeferencing, not sensor RPC, relief correction, or full
    orthorectification. Checkpoints never participate in the fit.
    """
    crs=CRS.from_epsg(epsg)
    require(crs.is_projected and all(abs(a.unit_conversion_factor-1)<1e-10 for a in crs.axis_info[:2]),"Use a projected metre CRS.")
    a=np.asarray(controls,float);b=np.asarray(checkpoints,float)
    require(a.ndim==b.ndim==2 and a.shape[1]==b.shape[1]==4 and 4<=len(a)<=10000 and 3<=len(b)<=10000,
        "Provide 4–10,000 control and 3–10,000 checkpoint rows [column,row,x_m,y_m].")
    require(np.isfinite(a).all() and np.isfinite(b).all() and max(np.max(abs(a)),np.max(abs(b)))<=1e9,"Invalid control coordinates.")
    require(0<huber_m<=1e5 and 1<=iterations<=200 and 0<tolerance<=1e-3,"Invalid affine solver parameters.")
    require(len(set(map(tuple,a[:,:2])))==len(a) and len(set(map(tuple,b[:,:2])))==len(b),"Duplicate image points.")
    require(not set(map(tuple,a[:,:2]))&set(map(tuple,b[:,:2])),"Control and checkpoint image locations must be disjoint.")
    center=a[:,:2].mean(axis=0);scale=a[:,:2].std(axis=0);world=a[:,2:].mean(axis=0)
    require(np.all(scale>0),"Control positions are degenerate.")
    design=np.column_stack(((a[:,:2]-center)/scale,np.ones(len(a))))
    target=a[:,2:]-world
    beta,_,rank,s=np.linalg.lstsq(design,target,rcond=1e-12)
    require(rank==3,"Control positions are collinear.")
    converged=False
    for i in range(iterations):
        error=np.linalg.norm(design@beta-target,axis=1)
        w=np.minimum(1.,huber_m/np.maximum(error,1e-15))
        new,_,rank,s=np.linalg.lstsq(design*np.sqrt(w[:,None]),target*np.sqrt(w[:,None]),rcond=1e-12)
        require(rank==3,"Weighted affine system is singular.")
        step=float(np.max(np.abs(new-beta)))
        beta=new
        if step<=tolerance*max(1.,float(np.max(np.abs(beta)))):
            converged=True;break
    linear=beta[:2].T/scale
    shift=world+beta[2]-linear@center
    sv=np.linalg.svd(linear,compute_uv=False)
    require(sv[-1]>sv[0]*1e-10,"Fitted map transform is singular.")
    def residual(points):
        pred=points[:,:2]@linear.T+shift
        return pred-points[:,2:]
    e=residual(a);q=residual(b);r=np.linalg.norm(q,axis=1)
    # Rasterio transform maps pixel corners. GCP coordinates denote integer
    # pixel centers, so shift the origin by half a pixel on both axes.
    corner=shift-linear@np.array([.5,.5])
    return {"crs":crs.to_string(),"affine":[float(linear[0,0]),float(linear[0,1]),float(corner[0]),
        float(linear[1,0]),float(linear[1,1]),float(corner[1])],
        "pixel_coordinate_convention":"integer column/row denotes pixel center; output affine uses pixel corner convention",
        "control_count":len(a),"checkpoint_count":len(b),"iterations":i+1,"converged":converged,
        "weighted_design_condition":float(s[0]/s[-1]),"control_rmse_m":float(np.sqrt(np.mean(np.sum(e*e,axis=1)))),
        "checkpoint_rmse_m":float(np.sqrt(np.mean(r*r))),"checkpoint_axis_rmse_m":np.sqrt(np.mean(q*q,axis=0)).tolist(),
        "checkpoint_bias_m":q.mean(axis=0).tolist(),"checkpoint_p95_radial_error_m":float(np.quantile(r,.95)),
        "checkpoint_residuals_m":q.tolist(),"assumption":"operator-supplied independent checkpoints; affine model only, no terrain displacement correction"}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path)
    args=parser.parse_args()
    raw=args.config.read_bytes();result=fit_affine(**json.loads(raw))
    result["input_sha256"]=hashlib.sha256(raw).hexdigest()
    print(json.dumps(result,indent=2,allow_nan=False))

if __name__=="__main__":main()
