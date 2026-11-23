"""Georeferenced RGB raster draping; no fabricated imagery outside coverage."""
import base64
import io
import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from imagery.raster import RasterError
from .cancellation import checkpoint

def mesh_texture(path,affine,crs,rows,cols,step,cancel=None):
    if rows<2 or cols<2:raise RasterError("Terrain texture needs at least two samples per axis.")
    left,top=affine*(.5,.5)
    right,bottom=affine*((cols-1)*step+.5,(rows-1)*step+.5)
    width=512;height=max(2,round(width*(top-bottom)/(right-left)))
    if height>512:width=max(2,round(width*512/height));height=512
    target=from_bounds(left,bottom,right,top,width,height)
    rgb=np.full((3,height,width),np.nan,dtype=np.float32)
    with rasterio.open(path) as source:
        if source.count<3 or not source.crs:raise RasterError("Texture must be a georeferenced RGB raster.")
        for i in range(3):
            checkpoint(cancel)
            reproject(rasterio.band(source,i+1),rgb[i],dst_transform=target,dst_crs=crs,
                      dst_nodata=float("nan"),resampling=Resampling.bilinear)
        good=np.isfinite(rgb).all(axis=0)
        if not good.any():raise RasterError("Texture does not overlap the terrain mesh.")
        pixels=np.zeros((height,width,4),dtype=np.uint8)
        for i in range(3):
            values=rgb[i,good]
            if source.dtypes[i]=="uint8":low,high=0.,255.
            else:low,high=np.percentile(values,[2,98]);high=max(high,low+1)
            pixels[:,:,i][good]=np.clip((values-low)/(high-low)*255,0,255).astype(np.uint8)
        pixels[:,:,3][good]=255
    output=io.BytesIO();Image.fromarray(pixels).save(output,format="PNG")
    return {"png":"data:image/png;base64,"+base64.b64encode(output.getvalue()).decode("ascii"),
            "coverage_pct":float(100*good.mean())}
