"""Conditional weighted InSAR acquisition-network inversion for corrected phase pairs.

Input is already coregistered, unwrapped and externally corrected. No orbit,
topographic, atmospheric, phase-unwrapping or spatial reference correction is
inferred by this module.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
import rasterio
from .remote_windowed import digest,windows
from analysis.science_raster import require

def design(times,pairs,sigma):
    t=np.asarray(times,float);q=np.asarray(pairs);sd=np.asarray(sigma,float)
    require(t.ndim==1 and 3<=len(t)<=32 and np.isfinite(t).all() and np.all(np.diff(t)>0),"Provide 3–32 ordered acquisition times.")
    require(q.ndim==2 and q.shape[1]==2 and len(t)-1<=len(q)<=96 and np.issubdtype(q.dtype,np.integer),"Provide 2–96 integer acquisition index pairs.")
    require(np.all((q>=0)&(q<len(t))) and np.all(q[:,0]<q[:,1]) and len(set(map(tuple,q)))==len(q),"Pairs must be unique, forward and in range.")
    require(sd.shape==(len(q),) and np.isfinite(sd).all() and np.all((sd>=1e-6)&(sd<=1e6)),"One positive phase standard deviation per pair (radians).")
    a=np.zeros((len(q),len(t)))
    a[np.arange(len(q)),q[:,0]]=-1
    a[np.arange(len(q)),q[:,1]]=1
    a=a[:,1:]
    require(np.linalg.matrix_rank(a)==len(t)-1,"Acquisition graph is disconnected from the first date.")
    return a,sd

def invert(phase,times,pairs,sigma,wavelength,range_sign):
    """Recover first-epoch-relative LOS range for fully identifiable pixels.

    Independent, known phase-error standard deviations are conditional inputs.
    Missing pairs are allowed, but all epochs must remain connected to the
    reference date. Returns displacement, conditional SD, chi-square and dof.
    """
    a,sd=design(times,pairs,sigma)
    z=np.asarray(phase,float)
    require(z.ndim==3 and z.shape[0]==len(a) and z.size<=8_000_000 and not np.isinf(z).any(),"Invalid phase cube or memory budget.")
    require(math.isfinite(wavelength) and .001<=wavelength<=10 and range_sign in (-1,1),"Specify radar wavelength (m) and signed phase-to-range convention.")
    h,w=z.shape[1:];n=len(times)-1
    flat=z.reshape(len(a),-1)
    mask=np.isfinite(flat)
    patterns,ids=np.unique(np.packbits(mask.T,axis=1),axis=0,return_inverse=True)
    require(len(patterns)<=4096,"Too many missing-pair patterns; reduce window size.")
    require(len(patterns)*len(a)*n*n+flat.shape[1]*len(a)*n<=300_000_000,"InSAR inverse work budget exceeded.")
    out=np.full((2*n+2,h*w),np.nan)
    # Sort once, rather than scanning the full pixel population for each pattern.
    ordered=np.argsort(ids,kind="stable")
    groups=np.split(ordered,np.cumsum(np.bincount(ids))[:-1])
    factor=range_sign*wavelength/(4*np.pi)
    identifiable=0
    for pattern,columns in zip(patterns,groups):
        good=np.unpackbits(pattern)[:len(a)].astype(bool)
        if good.sum()<n:continue
        aw=a[good]/sd[good,None]
        u,s,vt=np.linalg.svd(aw,full_matrices=False)
        if len(s)<n or s[-1]<=s[0]*1e-10:continue
        pinv=(vt.T/s)@u.T
        y=flat[np.ix_(good,columns)]/sd[good,None]
        x=pinv@y
        error=aw@x-y
        out[:n,columns]=factor*x
        out[n:2*n,columns]=abs(factor)*np.sqrt(np.sum(pinv**2,axis=1))[:,None]
        out[2*n,columns]=np.sum(error**2,axis=0)
        out[2*n+1,columns]=int(good.sum())-n
        identifiable+=len(columns)
    return out.reshape(2*n+2,h,w),{"identifiable_cells":identifiable,"unidentified_cells":h*w-identifiable,
        "missingness_patterns":len(patterns),"reference_time":float(times[0]),"phase_to_range_m_per_rad":factor,
        "assumptions":"independent supplied phase errors; already corrected unwrapped phase; no atmospheric, orbit, DEM or shared-acquisition covariance correction"}

def process(input_path,output,times,pairs,sigma,wavelength,range_sign,tile=64):
    a,_=design(times,pairs,sigma)
    require(isinstance(tile,int) and 16<=tile<=256,"Tile must be 16–256.")
    input_path,output=Path(input_path).resolve(),Path(output).resolve()
    require(input_path!=output and not output.exists() and output.parent.is_dir(),"Output must be a new file.")
    input_hash=digest(input_path);tmp=None
    try:
        with rasterio.open(input_path) as src:
            require(src.driver=="GTiff" and src.crs and src.count==len(a),"Use one georeferenced unwrapped-phase band per pair in the specified order.")
            n=len(times)-1
            fd,name=tempfile.mkstemp(prefix=".insar-",suffix=".tif",dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver="GTiff",width=src.width,height=src.height,count=2*n+2,dtype="float64",crs=src.crs,
                transform=src.transform,nodata=np.nan,compress="deflate",tiled=True,blockxsize=128,blockysize=128,BIGTIFF="IF_SAFER")
            total=0
            with rasterio.open(tmp,"w",**profile) as dst:
                dst.update_tags(REFERENCE_TIME=str(times[0]),METHOD="conditional_insar_network_wls",PHASE_UNIT="radian")
                for i,t in enumerate(times[1:]):
                    dst.set_band_description(i+1,f"relative_range_m_at_{t}")
                    dst.set_band_description(n+i+1,f"conditional_sd_m_at_{t}")
                    dst.update_tags(i+1,TERRAIN_UNIT="m");dst.update_tags(n+i+1,TERRAIN_UNIT="m")
                dst.set_band_description(2*n+1,"weighted_residual_chi_square")
                dst.set_band_description(2*n+2,"residual_degrees_of_freedom")
                for win in windows(src.width,src.height,tile):
                    z=src.read(window=win,masked=True).astype(float).filled(np.nan)
                    for i,(scale,offset) in enumerate(zip(src.scales,src.offsets)):
                        tag=src.tags(i+1).get("TERRAIN_UNIT") or src.units[i] or src.tags().get("TERRAIN_UNIT")
                        require(not tag or tag in ("radian","rad"),"Phase band unit conflicts with radians.")
                        z[i]=z[i]*scale+offset
                    result,meta=invert(z,times,pairs,sigma,wavelength,range_sign)
                    total+=meta["identifiable_cells"]
                    dst.write(result,window=win)
            require(total>0,"No pixel has an identifiable acquisition graph.")
            require(digest(input_path)==input_hash,"Input changed during processing.")
            receipt={"input_sha256":input_hash,"output_sha256":digest(tmp),"times":times,"pairs":pairs,"sigma_rad":sigma,
                "wavelength_m":wavelength,"range_sign":range_sign,"identifiable_cells":total,
                "unidentified_cells":src.width*src.height-total,"crs":str(src.crs),"transform":list(src.transform)[:6],
                "assumption":"independent pair errors; corrected unwrapped phase; not a full SBAS processing chain"}
            os.link(tmp,output);return receipt
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(json.dumps(process(output=args.output,**json.loads(args.config.read_text(encoding="utf8"))),indent=2,allow_nan=False))

if __name__=="__main__":main()
