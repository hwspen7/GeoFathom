"""Native Landsat 8/9 Collection 2 Level-1 radiometric calibration.

USGS: https://www.usgs.gov/landsat-missions/using-usgs-landsat-level-1-data-product
USGS QA: https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands
"""
import argparse
import json
import math
import os
import tempfile
from pathlib import Path
import numpy as np
import rasterio
from .remote_windowed import digest,windows,same_grid
from analysis.science_raster import require

def calibration(metadata,band,product):
    """Validate exact Collection 2 Level-1 MTL groups and per-band coefficients."""
    root=metadata.get("LANDSAT_METADATA_FILE")
    require(isinstance(root,dict),"Expected official LANDSAT_METADATA_FILE JSON.")
    contents=root.get("PRODUCT_CONTENTS",{});attributes=root.get("IMAGE_ATTRIBUTES",{})
    rad=root.get("LEVEL1_RADIOMETRIC_RESCALING",{});thermal=root.get("LEVEL1_THERMAL_CONSTANTS",{})
    require(str(contents.get("COLLECTION_NUMBER")) in ("2","02") and contents.get("PROCESSING_LEVEL") in ("L1TP","L1GT","L1GS"),"Use Collection 2 Level-1 product metadata.")
    require(attributes.get("SPACECRAFT_ID") in ("LANDSAT_8","LANDSAT_9"),"Only Landsat 8/9 OLI/TIRS is supported.")
    require(isinstance(band,int) and not isinstance(band,bool) and band in (1,2,3,4,5,6,7,9,10,11),"Use native 30 m product bands; panchromatic band 8 requires a separate QA grid.")
    require(product in ("reflectance","radiance","brightness_temperature"),"Unknown Level-1 output product.")
    require(product!="reflectance" or band<=9,"TOA reflectance requires an OLI band.")
    require(product!="brightness_temperature" or band in (10,11),"Brightness temperature requires a TIRS band.")
    def number(obj,key,positive=False):
        try:x=float(obj[key])
        except (KeyError,TypeError,ValueError) as e:raise ValueError("Missing or invalid MTL coefficient: "+key) from e
        require(math.isfinite(x) and (not positive or x>0),"Invalid MTL coefficient: "+key)
        return x
    prefix="REFLECTANCE" if product=="reflectance" else "RADIANCE"
    gain=number(rad,f"{prefix}_MULT_BAND_{band}",True);offset=number(rad,f"{prefix}_ADD_BAND_{band}")
    sun=number(attributes,"SUN_ELEVATION")
    require(0<sun<=90,"Invalid scene solar elevation.")
    out={"band":band,"product":product,"spacecraft":attributes["SPACECRAFT_ID"],"product_id":contents.get("LANDSAT_PRODUCT_ID"),
         "gain":gain,"offset":offset,"scene_sun_elevation_deg":sun,"unit":"reflectance" if product=="reflectance" else "K" if product=="brightness_temperature" else "radiance"}
    if product=="brightness_temperature":
        out.update(k1=number(thermal,f"K1_CONSTANT_BAND_{band}",True),k2=number(thermal,f"K2_CONSTANT_BAND_{band}",True))
    keys={"image":f"FILE_NAME_BAND_{band}","pixel_qa":"FILE_NAME_QUALITY_L1_PIXEL","saturation_qa":"FILE_NAME_QUALITY_L1_RADIOMETRIC_SATURATION"}
    for name,key in keys.items():
        value=contents.get(key)
        require(isinstance(value,str) and Path(value).name==value and "/" not in value and "\\" not in value and value.lower().endswith(".tif"),"Invalid or absent native MTL filename: "+key)
        out[name]=value
    return out

def calibrate(dn,qa,radsat,c,solar_elevation=None):
    """Return masked physical product; per-pixel solar elevation is optional."""
    z=np.asarray(dn,float);q=np.asarray(qa,float);r=np.asarray(radsat,float)
    require(z.shape==q.shape==r.shape,"QA and DN grids must match.")
    for x in (z,q,r):
        good=np.isfinite(x);require(np.all((x[good]>=0)&(x[good]<=65535)&(x[good]==np.floor(x[good]))),"Expected original uint16 DN and QA values.")
    qbits=np.where(np.isfinite(q),q,0).astype(np.uint16)
    # Reject fill, dilated clouds, cirrus, cloud, cloud shadow and snow.
    # Reject any radiometric-saturation/terrain-occlusion flag conservatively.
    valid=np.isfinite(z)&np.isfinite(q)&np.isfinite(r)&(z>0)&((qbits&63)==0)&(r==0)
    value=c["gain"]*z+c["offset"]
    if c["product"]=="reflectance":
        angle=np.asarray(c["scene_sun_elevation_deg"] if solar_elevation is None else solar_elevation,float)
        require(angle.ndim==0 or angle.shape==z.shape,"Solar angle grid must match DN.")
        good=np.isfinite(angle)&(angle>0)&(angle<=90)
        valid &= good
        value=np.divide(value,np.sin(np.deg2rad(angle)),out=np.full(z.shape,np.nan),where=good)
        valid &= (value>=-.2)&(value<=1.6)
    elif c["product"]=="brightness_temperature":
        valid &= value>0
        value=np.divide(c["k2"],np.log1p(np.divide(c["k1"],value,out=np.full(z.shape,np.nan),where=value>0)),
                        out=np.full(z.shape,np.nan),where=value>0)
    else:valid &= value>=0
    return np.where(valid&np.isfinite(value),value,np.nan)

def process(mtl_path,output,band,product,*,tile=256,solar_elevation_path=None):
    """Stream original metadata-bound rasters; no implicit reprojection."""
    mtl_path,output=Path(mtl_path).resolve(),Path(output).resolve()
    require(isinstance(tile,int) and 16<=tile<=1024 and not output.exists() and output.parent.is_dir(),"Invalid tile or output path.")
    require(mtl_path.stat().st_size<=2_000_000,"MTL JSON exceeds two MB.")
    raw=mtl_path.read_bytes();c=calibration(json.loads(raw),band,product)
    paths={k:mtl_path.parent/c[k] for k in ("image","pixel_qa","saturation_qa")}
    paths["mtl"]=mtl_path
    if solar_elevation_path is not None:
        require(product=="reflectance","Solar elevation applies only to reflectance.")
        paths["solar_elevation"]=Path(solar_elevation_path).resolve()
    require(output not in [p.resolve() for p in paths.values()],"Output cannot overwrite a source.")
    hashes={k:digest(p) for k,p in paths.items()};tmp=None
    try:
        from contextlib import ExitStack
        with ExitStack() as ctx:
            src,qa,sat=[ctx.enter_context(rasterio.open(paths[k])) for k in ("image","pixel_qa","saturation_qa")]
            require(src.crs and all(ds.driver=="GTiff" and ds.count==1 and same_grid(src,ds) for ds in (src,qa,sat)),"Original band and QA must share the exact native georeferenced grid.")
            require(all(ds.dtypes[0]=="uint16" and (ds.scales[0],ds.offsets[0])==(1.,0.) for ds in (src,qa,sat)),"Expected unscaled original uint16 DN/QA GeoTIFF files.")
            angle=None
            if "solar_elevation" in paths:
                angle=ctx.enter_context(rasterio.open(paths["solar_elevation"]))
                require(angle.count==1 and same_grid(src,angle),"Solar elevation must match the exact native grid.")
                unit=angle.tags(1).get("TERRAIN_UNIT") or angle.units[0] or angle.tags().get("TERRAIN_UNIT")
                require(unit in ("degree","degrees","deg"),"Solar elevation requires explicit degree units.")
                require(math.isfinite(angle.scales[0]) and angle.scales[0]>0 and math.isfinite(angle.offsets[0]),"Invalid angle calibration.")
            fd,name=tempfile.mkstemp(prefix=".landsat-",suffix=".tif",dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver="GTiff",width=src.width,height=src.height,count=1,dtype="float64",crs=src.crs,
                transform=src.transform,nodata=np.nan,compress="deflate",tiled=True,blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
            total=0
            with rasterio.open(tmp,"w",**profile) as dst:
                dst.update_tags(TERRAIN_UNIT=c["unit"],REMOTE_METHOD="landsat_collection2_level1",LANDSAT_PRODUCT_ID=str(c["product_id"] or ""))
                for win in windows(src.width,src.height,tile):
                    values=[ds.read(1,window=win,masked=True).astype(float).filled(np.nan) for ds in (src,qa,sat)]
                    elevation=angle.read(1,window=win,masked=True).astype(float).filled(np.nan)*angle.scales[0]+angle.offsets[0] if angle is not None else None
                    out=calibrate(*values,c,elevation);total+=int(np.isfinite(out).sum())
                    dst.write(out,1,window=win)
            require(total>0,"No valid calibrated pixels.")
            require(hashes=={k:digest(p) for k,p in paths.items()},"Source changed during calibration.")
            receipt={"input_sha256":hashes,"output_sha256":digest(tmp),"calibration":c,"valid_cells":total,
                "crs":str(src.crs),"transform":list(src.transform)[:6],"solar_elevation":"per-pixel supplied" if angle else "scene-center metadata",
                "qa_policy":"QA_PIXEL bits 0–5 and all nonzero QA_RADSAT rejected",
                "assumption":"TOA radiance/reflectance or at-sensor brightness temperature; not surface reflectance or land surface temperature"}
            os.link(tmp,output);return receipt
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(json.dumps(process(output=args.output,**json.loads(args.config.read_text(encoding="utf8"))),indent=2,allow_nan=False))

if __name__=="__main__":main()
