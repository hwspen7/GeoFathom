"""Windowed RPC orthorectification using explicit ellipsoidal DEM heights."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import rasterio
from rasterio.transform import RPCTransformer
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from rasterio.windows import Window
from pyproj import Transformer
from .remote_band import read_calibrated
from .remote_windowed import windows,digest
from analysis.science_raster import require

def rectify(input_path,dem_path,target_path,output,*,height_reference,source_band=1,dem_band=1,
            unit="",quantity="numeric",resampling="bilinear",tile=128):
    """Map each target pixel center through DEM height and RPC into the sensor.

    DEM must already contain WGS84 ellipsoidal heights in metres, not an
    orthometric geoid-referenced elevation. Nearest DEM sampling and strict
    image interpolation are explicit. No automatic vertical datum conversion
    or independent geometric calibration is implied.
    """
    require(height_reference=="WGS84_ellipsoid_m","Explicit WGS84 ellipsoidal heights in metres required.")
    require(quantity in ("numeric","reflectance","class") and resampling in ("nearest","bilinear") and isinstance(tile,int) and 16<=tile<=512,"Invalid RPC configuration.")
    require(quantity!="class" or resampling=="nearest","Classes require nearest-neighbor image sampling.")
    srcpath,dempath,gridpath,output=map(lambda x:Path(x).resolve(),(input_path,dem_path,target_path,output))
    require(output not in (srcpath,dempath,gridpath) and not output.exists() and output.parent.is_dir(),"Output must be a new file.")
    hashes={k:digest(p) for k,p in zip(("image","dem","target"),(srcpath,dempath,gridpath))}
    tmp=None
    try:
        with rasterio.open(srcpath) as src,rasterio.open(dempath) as dem,rasterio.open(gridpath) as grid:
            rpc=src.rpcs
            require(rpc is not None and dem.crs and grid.crs,"Input RPC metadata, georeferenced DEM and target grid required.")
            require(1<=source_band<=src.count and 1<=dem_band<=dem.count,"Invalid source or DEM band.")
            require(all(np.isfinite(x) and x>0 for x in (rpc.lat_scale,rpc.long_scale,rpc.height_scale,rpc.line_scale,rpc.samp_scale)),"Invalid RPC scale coefficients.")
            for a in (rpc.line_num_coeff,rpc.line_den_coeff,rpc.samp_num_coeff,rpc.samp_den_coeff):
                require(len(a)==20 and np.isfinite(a).all(),"Invalid RPC polynomial coefficients.")
            require(all(np.isfinite(x) for x in (rpc.lat_off,rpc.long_off,rpc.height_off,rpc.line_off,rpc.samp_off)),"Invalid RPC offsets.")
            a=grid.transform
            require(a.b==a.d==0 and a.a>0 and a.e<0,"Target must be a north-up grid.")
            tag=dem.tags(dem_band).get("TERRAIN_UNIT") or dem.units[dem_band-1] or dem.tags().get("TERRAIN_UNIT")
            require(not tag or tag in ("m","metre","meter"),"DEM unit must be metres.")
            scale,offset=float(dem.scales[dem_band-1]),float(dem.offsets[dem_band-1])
            require(np.isfinite(scale) and scale>0 and np.isfinite(offset),"Invalid DEM calibration.")
            bind=SimpleNamespace(band=source_band,encoding="metadata",unit=unit,scale=1.,offset=0.)
            _,physical_unit,ss,so=read_calibrated(src,bind,quantity,Window(0,0,1,1))
            tx=Transformer.from_crs(grid.crs,4326,always_xy=True)
            fd,name=tempfile.mkstemp(prefix=".rpc-",suffix=".tif",dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver="GTiff",width=grid.width,height=grid.height,count=1,dtype="float64",crs=grid.crs,
                transform=a,nodata=np.nan,compress="deflate",tiled=True,blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
            valid_count=0;missing_dem=0;outside_model=0;outside_image=0;max_window=0
            with WarpedVRT(dem,crs=grid.crs,transform=a,width=grid.width,height=grid.height,
                           dtype="float64",nodata=np.nan,resampling=Resampling.nearest) as height, RPCTransformer(rpc) as model, rasterio.open(tmp,"w",**profile) as dst:
                dst.update_tags(TERRAIN_UNIT=physical_unit,REMOTE_METHOD="rpc_dem_orthorectification",HEIGHT_REFERENCE=height_reference)
                for win in windows(grid.width,grid.height,tile):
                    h,w=int(win.height),int(win.width)
                    mask=np.isfinite(grid.read(1,window=win,masked=True).astype(float).filled(np.nan))
                    z=height.read(dem_band,window=win,masked=True).astype(float).filled(np.nan)*scale+offset
                    missing_dem+=int((mask&~np.isfinite(z)).sum())
                    rr,cc=np.indices((h,w),dtype=float)
                    lon,lat=tx.transform(a.c+(cc+win.col_off+.5)*a.a,a.f+(rr+win.row_off+.5)*a.e)
                    # RPCs are normalized over the stated support; avoid extrapolation.
                    domain=(np.abs((lon-rpc.long_off)/rpc.long_scale)<=1.1)&(np.abs((lat-rpc.lat_off)/rpc.lat_scale)<=1.1)&(np.abs((z-rpc.height_off)/rpc.height_scale)<=1.1)
                    good=mask&np.isfinite(z)&domain
                    outside_model+=int((mask&np.isfinite(z)&~domain).sum())
                    pos=np.flatnonzero(good)
                    out=np.full((h,w),np.nan)
                    if len(pos):
                        row,col=model.rowcol(lon.flat[pos],lat.flat[pos],zs=z.flat[pos],op=lambda x:x)
                        row,col=np.asarray(row),np.asarray(col)
                        inside=np.isfinite(row)&np.isfinite(col)&(row>=0)&(row<src.height)&(col>=0)&(col<src.width)
                        outside_image+=int((~inside).sum())
                        row,col,pos=row[inside],col[inside],pos[inside]
                        if len(pos):
                            if resampling=="nearest":
                                r=np.floor(row).astype(int);c=np.floor(col).astype(int)
                                r0,r1,c0,c1=int(r.min()),int(r.max()+1),int(c.min()),int(c.max()+1)
                            else:
                                # GDAL fractional coordinates use pixel corners.
                                # Interpolate in center-index coordinates.
                                y=row-.5;x=col-.5;r=np.floor(y).astype(int);c=np.floor(x).astype(int)
                                r0,r1=max(0,int(r.min())),min(src.height,int(r.max()+2))
                                c0,c1=max(0,int(c.min())),min(src.width,int(c.max()+2))
                            cells=(r1-r0)*(c1-c0)
                            require(0<cells<=2_000_000,"RPC source support window exceeds two million cells; reduce tile size.")
                            max_window=max(max_window,cells)
                            data=read_calibrated(src,bind,quantity,Window(c0,r0,c1-c0,r1-r0))[0]
                            if resampling=="nearest":
                                out.flat[pos]=data[r-r0,c-c0]
                            else:
                                result=np.zeros(len(pos));supported=np.ones(len(pos),bool)
                                for dr in (0,1):
                                    for dc in (0,1):
                                        weight=(y-r if dr else 1-(y-r))*(x-c if dc else 1-(x-c))
                                        ri=r+dr-r0;ci=c+dc-c0
                                        within=(ri>=0)&(ri<data.shape[0])&(ci>=0)&(ci<data.shape[1])
                                        value=data[np.clip(ri,0,data.shape[0]-1),np.clip(ci,0,data.shape[1]-1)]
                                        active=weight>1e-12
                                        supported &= (~active)|(within&np.isfinite(value))
                                        result+=np.where(active&within&np.isfinite(value),weight*value,0.)
                                out.flat[pos]=np.where(supported,result,np.nan)
                    dst.write(out,1,window=win);valid_count+=int(np.isfinite(out).sum())
            require(valid_count>0,"No target pixel has valid RPC and DEM support.")
            require(hashes=={k:digest(p) for k,p in zip(("image","dem","target"),(srcpath,dempath,gridpath))},"An input changed during orthorectification.")
            receipt={"input_sha256":hashes,"output_sha256":digest(tmp),"valid_cells":valid_count,"missing_dem_cells":missing_dem,
                "outside_rpc_domain_cells":outside_model,"outside_sensor_cells":outside_image,"maximum_source_window_cells":max_window,
                "rpc":rpc.to_gdal(),"height_reference":height_reference,"dem_resampling":"nearest","image_resampling":resampling,
                "image_scale":ss,"image_offset":so,"unit":physical_unit,"source_band":source_band,"dem_band":dem_band,
                "target_crs":str(grid.crs),"target_transform":list(a)[:6],"domain_limit_normalized":1.1,
                "assumption":"WGS84 ellipsoidal DEM heights, supplied RPC, target pixel centers; no terrain occlusion, bias correction or independent accuracy claim"}
            os.link(tmp,output);return receipt
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(json.dumps(rectify(output=args.output,**json.loads(args.config.read_text(encoding="utf8"))),indent=2,allow_nan=False))

if __name__=="__main__":main()
