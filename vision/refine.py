"""WGS84 positive/negative clicks and a rectangular box for optional SAM2.

Prompt coordinates are transformed to the original raster window pixel CRS.
This adapter never makes unstated assumptions about map screen pixels.
"""
from pathlib import Path

import numpy as np
from pyproj import Transformer

from imagery.raster import RasterError,read_rgb_window
from .sam import sam_mask
from .trace import _vectorize


def refine_raster(path:Path,image_id:str,anchor:list[float],
                  positives:list[list[float]],negatives:list[list[float]],
                  box:list[list[float]]|None=None,window_size:int=512):
    if not 1<=len(positives)<=20 or len(negatives)>20:
        raise RasterError("SAM refinement requires 1–20 positive and up to 20 negative points.")
    image,seed_x,seed_y,affine,crs=read_rgb_window(
        path,anchor[0],anchor[1],window_size,
    )
    to_source=Transformer.from_crs("EPSG:4326",crs,always_xy=True)
    inverse=~affine
    def pixel(position):
        if len(position)!=2 or not all(np.isfinite(v) for v in position):
            raise RasterError("SAM prompts require valid WGS84 positions.")
        x,y=to_source.transform(*position)
        col,row=inverse*(x,y)
        if not (0<=col<image.shape[1] and 0<=row<image.shape[0]):
            raise RasterError("SAM prompt is outside the current original-pixel image window.")
        return [float(col),float(row)]
    positive_xy=[pixel(item) for item in positives]
    negative_xy=[pixel(item) for item in negatives]
    rectangle=None
    if box is not None:
        if len(box)!=2:raise RasterError("Box requires two corner points.")
        first,second=pixel(box[0]),pixel(box[1])
        rectangle=[min(first[0],second[0]),min(first[1],second[1]),
                   max(first[0],second[0]),max(first[1],second[1])]
        if rectangle[2]-rectangle[0]<2 or rectangle[3]-rectangle[1]<2:
            raise RasterError("Prompt rectangle is smaller than two source pixels.")
    mask,confidence,model=sam_mask(
        image,seed_x,seed_y,positive=positive_xy,negative=negative_xy,box=rectangle,
    )
    if mask.shape!=image.shape[:2]:
        raise RasterError("SAM returned an invalid prediction mask dimension.")
    # Inverse affine coordinates refer to pixel cells, not pixel centres.
    # Rounding a valid coordinate near the last column could access width.
    if not mask[int(positive_xy[0][1]),int(positive_xy[0][0])]:
        raise RasterError("The mask does not contain the positive anchor.")
    output=_vectorize(mask,affine,crs)
    return {
        **output,"image_id":image_id,"provider":"sam2","engine":"sam2-prompt-refinement",
        "model_id":model,"confidence":confidence,
        "positive_count":len(positives),"negative_count":len(negatives),
        "box_used":rectangle is not None,
        "pixel_count":int(mask.sum()),"source_crs":crs,"geometry_crs":"EPSG:4326",
        "boundary_status":"estimated_from_imagery",
        "warning":"AI prompt refinement is estimated from imagery and requires manual review.",
    }
