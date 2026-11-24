"""Windowed conservative transfer of satellite observations between local grids."""
import argparse
import json
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import numpy as np
import rasterio
from rasterio.windows import Window
from pyproj import CRS
from .remote_band import read_calibrated
from .remote_satellite import area_overlap
from .remote_windowed import digest,windows
from analysis.science_raster import require

def _metric(ds):
    crs=CRS.from_user_input(ds.crs)
    return crs.is_projected and all(abs(x.unit_conversion_factor-1)<1e-10 for x in crs.axis_info[:2])

def transfer(source_path,target_path,output,*,mode="mean",minimum_coverage=.8,tile=256,source_band=1,target_band=1,unit="",encoding="metadata",scale=1.,offset=0.):
    """Exact area support on the target native grid, without full-scene arrays.

    The target band supplies a validity mask only. The output uses the source
    physical units (or fraction). A source-window budget is enforced before
    reading and an atomic no-overwrite link publishes completed output.
    """
    require(mode in ("mean","coverage") and 0<=minimum_coverage<=1 and 16<=tile<=512 and isinstance(tile,int),"Invalid overlap configuration.")
    require(encoding in {"metadata","raw","custom","landsat_sr","landsat_st"},"Unsupported source calibration encoding.")
    source_path,target_path,output=map(lambda p:Path(p).resolve(),(source_path,target_path,output))
    require(output not in (source_path,target_path) and not output.exists() and output.parent.is_dir(),"Output must be a new file in an existing directory.")
    fingerprints={"source_sha256":digest(source_path),"target_sha256":digest(target_path)}
    tmp=None
    try:
        with rasterio.open(source_path) as src,rasterio.open(target_path) as dstgrid:
            require(src.crs and dstgrid.crs and src.crs==dstgrid.crs and _metric(src),"Both grids need the same projected metre CRS.")
            require(1<=source_band<=src.count and 1<=target_band<=dstgrid.count,"Band number outside raster.")
            for ds in (src,dstgrid):
                a=ds.transform
                require(a.b==a.d==0 and a.a>0 and a.e<0,"Use north-up rectangular cells.")
            binding=SimpleNamespace(band=source_band,encoding=encoding,scale=scale,offset=offset,unit=unit)
            quantity="reflectance" if encoding=="landsat_sr" else "kelvin" if encoding=="landsat_st" else "numeric"
            _,physical_unit,actual_scale,actual_offset=read_calibrated(src,binding,quantity,Window(0,0,1,1))
            require(physical_unit!="class","Categorical values cannot be averaged.")
            kind="align_overlap_mean" if mode=="mean" else "align_overlap_coverage"
            fd,name=tempfile.mkstemp(prefix=".overlap-",suffix=".tif",dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver="GTiff",width=dstgrid.width,height=dstgrid.height,count=1,dtype="float64",crs=dstgrid.crs,
                transform=dstgrid.transform,nodata=np.nan,compress="deflate",tiled=True,blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
            count=0;support=0.;integral=0.;max_source_cells=0;tiles=0
            with rasterio.open(tmp,"w",**profile) as dst:
                dst.update_tags(TERRAIN_UNIT=physical_unit if mode=="mean" else "fraction",REMOTE_METHOD=kind)
                for win in windows(dstgrid.width,dstgrid.height,tile):
                    # Compute the source rectangle directly from target boundaries.
                    t=dstgrid.window_transform(win);h,w=int(win.height),int(win.width);a=src.transform
                    c0=max(0,math.floor((t.c-a.c)/a.a));c1=min(src.width,math.ceil((t.c+w*t.a-a.c)/a.a))
                    r0=max(0,math.floor((a.f-t.f)/(-a.e)));r1=min(src.height,math.ceil((a.f-(t.f+h*t.e))/(-a.e)))
                    valid=~np.ma.getmaskarray(dstgrid.read(target_band,window=win,masked=True))
                    target=SimpleNamespace(values=np.where(valid,1.,np.nan),transform=t,crs=src.crs,is_meter=True)
                    if c1<=c0 or r1<=r0:
                        z=np.where(valid,0.,np.nan) if mode=="coverage" else np.full((h,w),np.nan)
                    else:
                        cells=(r1-r0)*(c1-c0);require(cells<=2_000_000,"Source support window exceeds two million cells; reduce tile size.")
                        max_source_cells=max(max_source_cells,cells)
                        sw=Window(c0,r0,c1-c0,r1-r0)
                        values=read_calibrated(src,binding,quantity,sw)[0]
                        source=SimpleNamespace(values=values,transform=src.window_transform(sw),crs=src.crs,is_meter=True)
                        z,meta=area_overlap(source,target,{"minimum_coverage":minimum_coverage},kind)
                        support+=meta["observed_support_area_m2"];integral+=meta["observed_integral"]
                    dst.write(z,1,window=win);count+=int(np.isfinite(z).sum());tiles+=1
            require(count>0,"No valid output cells.")
            require(fingerprints=={"source_sha256":digest(source_path),"target_sha256":digest(target_path)},"Input changed during processing.")
            receipt={**fingerprints,"output_sha256":digest(tmp),"operation":kind,"valid_cells":count,"tiles":tiles,
                "maximum_source_window_cells":max_source_cells,"observed_support_area_m2":support,"observed_integral":integral,
                "source_band":source_band,"target_band":target_band,"source_unit":physical_unit,
                "scale":actual_scale,"offset":actual_offset,"minimum_coverage":minimum_coverage,
                "crs":str(dstgrid.crs),"transform":list(dstgrid.transform)[:6],"tile_size":tile}
            os.link(tmp,output)
            return receipt
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(json.dumps(transfer(output=args.output,**json.loads(args.config.read_text(encoding="utf8"))),indent=2,allow_nan=False))

if __name__=="__main__":main()
