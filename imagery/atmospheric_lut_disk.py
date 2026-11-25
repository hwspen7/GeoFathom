"""Disk-backed external-atmospheric-LUT correction of optical TOA reflectance."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import rasterio
from .remote_band import read_calibrated
from .remote_windowed import windows,digest,same_grid
from .satellite_lut_wishart import atmospheric_lut
from analysis.science_raster import require

def process(toa_path,aod_path,water_path,lut_path,output,*,tile=256,minimum_denominator=.01):
    require(isinstance(tile,int) and 16<=tile<=1024,"Invalid tile size.")
    paths={k:Path(v).resolve() for k,v in (("toa",toa_path),("aod",aod_path),("water",water_path),("lut",lut_path))}
    output=Path(output).resolve()
    require(output not in paths.values() and not output.exists() and output.parent.is_dir(),"Output must be new.")
    require(paths["lut"].stat().st_size<=8_000_000,"Atmospheric LUT exceeds eight MB.")
    hashes={k:digest(v) for k,v in paths.items()};lut=json.loads(paths["lut"].read_text(encoding="utf8"))
    # Validate physical axes and coefficients before opening the output.
    atmospheric_lut(np.array([np.nan]),np.array([np.nan]),np.array([np.nan]),lut,minimum_denominator)
    tmp=None
    try:
        with rasterio.open(paths["toa"]) as toa,rasterio.open(paths["aod"]) as aod,rasterio.open(paths["water"]) as water:
            require(toa.crs and all(x.count==1 and same_grid(toa,x) for x in (toa,aod,water)),"Explicitly align TOA and atmospheric grids.")
            bind=SimpleNamespace(band=1,encoding="metadata",scale=1.,offset=0.,unit="")
            def physical(ds,expected,win):
                tag=ds.tags(1).get("TERRAIN_UNIT") or ds.units[0] or ds.tags().get("TERRAIN_UNIT")
                require(tag==expected,"Declare atmospheric band units matching the LUT: "+expected)
                scale,offset=ds.scales[0],ds.offsets[0]
                require(np.isfinite(scale) and scale>0 and np.isfinite(offset),"Invalid atmospheric calibration.")
                return ds.read(1,window=win,masked=True).astype(float).filled(np.nan)*scale+offset
            fd,name=tempfile.mkstemp(prefix=".atmos-lut-",suffix=".tif",dir=output.parent);os.close(fd);tmp=Path(name)
            profile=dict(driver="GTiff",width=toa.width,height=toa.height,count=1,dtype="float64",crs=toa.crs,
                transform=toa.transform,nodata=np.nan,compress="deflate",tiled=True,blockxsize=256,blockysize=256,BIGTIFF="IF_SAFER")
            total=0;outside=0
            with rasterio.open(tmp,"w",**profile) as dst:
                dst.update_tags(TERRAIN_UNIT="reflectance",REMOTE_METHOD="external_atmospheric_lut")
                for win in windows(toa.width,toa.height,tile):
                    z=read_calibrated(toa,bind,"reflectance",win)[0]
                    a=physical(aod,"aod",win);w=physical(water,lut["water_unit"],win)
                    out,meta=atmospheric_lut(z,a,w,lut,minimum_denominator)
                    total+=meta["valid_cells"];outside+=meta["outside_lut_or_missing_cells"]
                    dst.write(out,1,window=win)
            require(total>0,"No supported LUT-corrected cells.")
            require(hashes=={k:digest(v) for k,v in paths.items()},"An atmospheric input changed during processing.")
            receipt={"input_sha256":hashes,"output_sha256":digest(tmp),"valid_cells":total,"outside_lut_or_missing_cells":outside,
                "model":lut["model"],"water_unit":lut["water_unit"],"aod_wavelength_nm":lut["aod_wavelength_nm"],
                "minimum_denominator":minimum_denominator,"crs":str(toa.crs),"transform":list(toa.transform)[:6],
                "assumption":"external fixed-geometry coefficient LUT, supplied aerosol and water observations, no atmospheric retrieval"}
            os.link(tmp,output);return receipt
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(json.dumps(process(output=args.output,**json.loads(args.config.read_text(encoding="utf8"))),indent=2,allow_nan=False))

if __name__=="__main__":main()
