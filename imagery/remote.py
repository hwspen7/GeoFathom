"""Allowlisted STAC-to-COG range reading and Sentinel-2 NDVI extraction.

This module never accepts arbitrary URLs from the API. A trusted STAC item
is resolved via Earth Search; band assets must belong to allowlisted HTTPS
hosts. GDAL reads only requested remote raster blocks via /vsicurl/.
"""
from contextlib import ExitStack
from math import ceil
import math
import os
import re
from urllib.parse import quote,unquote,urlsplit

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT

from geometry.spectral import normalized_difference
from imagery.raster import RasterError,_check
from vision.quality import sentinel2_clear_mask
from vision.tiled import TilePlan,_scratch,_disk_features,_check_scratch,_transitions,MAX_BOUNDARY_TRANSITIONS

_CATALOG="https://earth-search.aws.element84.com/v1"
_COLLECTIONS={"sentinel-2-c1-l2a","sentinel-2-l2a"}
_ITEM=re.compile(r"^[A-Za-z0-9_-]{8,140}$")
_ASSET=re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_DEFAULT_HOSTS=("e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com",)


def _approved_hosts():
    configured=os.getenv("GEOFATHOM_COG_ALLOWED_HOSTS","")
    hosts={host.strip().lower() for host in configured.split(",") if host.strip()}
    return hosts if hosts else set(_DEFAULT_HOSTS)


def vetted_asset_href(href):
    if not isinstance(href,str) or len(href)>1500:
        raise RasterError("Invalid remote COG asset URL.")
    parsed=urlsplit(href)
    host=(parsed.hostname or "").lower()
    if (parsed.scheme!="https" or parsed.port not in (None,443) or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or host not in _approved_hosts()):
        raise RasterError("Remote COG host or URL parameters are not approved.")
    decoded=unquote(parsed.path)
    if (not decoded.lower().endswith((".tif",".tiff")) or
            any(segment in (".","..") for segment in decoded.split("/"))
            or any(ord(ch)<32 for ch in decoded)
            or "\\" in decoded):
        raise RasterError("Remote COG must be a clean GeoTIFF path.")
    return href


def fetch_stac_item(collection,item_id):
    if collection not in _COLLECTIONS or not _ITEM.fullmatch(item_id):
        raise RasterError("Unknown STAC collection or invalid item identifier.")
    url=f"{_CATALOG}/collections/{quote(collection)}/items/{quote(item_id)}"
    with httpx.Client(timeout=20,follow_redirects=False) as http:
        with http.stream("GET",url,headers={"Accept":"application/geo+json"}) as response:
            response.raise_for_status()
            size=0
            content=bytearray()
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>1_000_000:
                    raise RasterError("STAC item metadata exceeds the size limit.")
                content.extend(chunk)
    import json
    item=json.loads(content)
    if (not isinstance(item,dict) or item.get("id")!=item_id
            or item.get("collection")!=collection
            or not isinstance(item.get("assets"),dict)):
        raise RasterError("STAC response does not match the requested item.")
    return item


def run_stac_ndvi(collection,item_id,threshold=.25,max_side=4096,
                  tile_size=256,max_pixels=16_777_216,memory_mb=32,
                  progress=None):
    if (not isinstance(threshold,(int,float)) or not math.isfinite(threshold)
            or not -1<threshold<1 or type(max_side) is not int
            or not 128<=max_side<=8192):
        raise RasterError("Invalid STAC spectral threshold or target resolution.")
    item=fetch_stac_item(collection,item_id)
    assets=item["assets"]
    names=("nir","red","scl")
    hrefs={}
    for name in names:
        obj=assets.get(name)
        if not isinstance(obj,dict):
            raise RasterError("STAC item lacks required NIR, red or SCL COG assets.")
        hrefs[name]=vetted_asset_href(obj.get("href"))
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                      GDAL_HTTP_MAX_RETRY="1",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
                      VSI_CACHE="FALSE"):
        with ExitStack() as opened:
            nir=opened.enter_context(rasterio.open("/vsicurl/"+hrefs["nir"]))
            red=opened.enter_context(rasterio.open("/vsicurl/"+hrefs["red"]))
            scl=opened.enter_context(rasterio.open("/vsicurl/"+hrefs["scl"]))
            for dataset in (nir,red,scl):
                _check(dataset)
                if dataset.count<1:
                    raise RasterError("A STAC spectral asset has no raster band.")
            output_width=min(nir.width,max_side)
            output_height=max(1,round(nir.height*output_width/nir.width))
            if output_height>max_side:
                output_height=max_side
                output_width=max(1,round(nir.width*output_height/nir.height))
            transform=nir.transform*Affine.scale(
                nir.width/output_width,nir.height/output_height)
            plan=TilePlan(output_width,output_height,tile_size,max_pixels,memory_mb)
            original_width,original_height=nir.width,nir.height
            original_crs=str(nir.crs)
            variables={
                "crs":nir.crs,"transform":transform,"width":output_width,
                "height":output_height,
            }
            red_aligned=opened.enter_context(WarpedVRT(
                red,resampling=Resampling.bilinear,**variables))
            nir_aligned=opened.enter_context(WarpedVRT(
                nir,resampling=Resampling.bilinear,**variables))
            scl_aligned=opened.enter_context(WarpedVRT(
                scl,resampling=Resampling.nearest,**variables))
            accepted_count=cloud_excluded=classified_count=transitions=0
            engine=None
            with _scratch(plan,"geofathom-stac-") as (temp,quota):
                output=temp/"stac-ndvi.tif"
                with rasterio.open(output,"w",driver="GTiff",
                                   width=output_width,height=output_height,
                                   count=1,dtype="uint8",crs=nir.crs,
                                   transform=transform,nodata=0,tiled=True,
                                   blockxsize=128,blockysize=128,
                                   compress="deflate") as target:
                    for i,window in enumerate(plan.windows(),1):
                        if progress:progress((i-1)/plan.count)
                        n=nir_aligned.read(1,window=window,masked=True)
                        r=red_aligned.read(1,window=window,masked=True)
                        q=scl_aligned.read(1,window=window,masked=True)
                        n_values=np.ma.asarray(n,dtype=np.float32).filled(np.nan)
                        r_values=np.ma.asarray(r,dtype=np.float32).filled(np.nan)
                        clear=sentinel2_clear_mask(np.asarray(q.filled(0),np.uint8))
                        valid=(~np.ma.getmaskarray(n) &
                               ~np.ma.getmaskarray(r) &
                               np.isfinite(n_values) & np.isfinite(r_values))
                        cloud_excluded+=int((valid & ~clear).sum())
                        score,usable,current=normalized_difference(
                            n_values,r_values,valid & clear)
                        engine=current if engine is None else (
                            engine if engine==current else "mixed")
                        labels=(usable & (score>=threshold)).astype(np.uint8)
                        transitions+=_transitions(labels)
                        if transitions>MAX_BOUNDARY_TRANSITIONS:
                            raise RasterError("STAC classification mask is too fragmented.")
                        target.write(labels,1,window=window)
                        accepted_count+=int(usable.sum())
                        classified_count+=int(labels.sum())
                        if i%16==0:_check_scratch(output,quota)
                _check_scratch(output,quota)
                if progress:progress(.93)
                features,truncated=_disk_features(
                    output,{1:"vegetation_candidate"},progress=progress)
    if progress:progress(1.)
    for feature in features:
        feature["properties"].update({
            "collection":collection,"stac_item_id":item_id,"index":"ndvi",
            "threshold":threshold})
    return {"type":"FeatureCollection","features":features,
            "analysis":"stac_ndvi","engine":"gdal-vsicurl+"+str(engine),
            "provider":"deterministic","model_id":None,
            "source":"Element84 Earth Search STAC + allowlisted HTTPS COG",
            "source_images":[],"stac_collection":collection,
            "stac_item_id":item_id,
            "asset_urls":hrefs,"acquired_at":(item.get("properties") or {}).get("datetime"),
            "source_crs":original_crs,"geometry_crs":"EPSG:4326",
            "pixel_grid":[output_width,output_height],
            "original_pixel_grid":[original_width,original_height],
            "resolution_reduced":(output_width,output_height)!=(original_width,original_height),
            "valid_pixels":accepted_count,
            "clear_pixels":accepted_count,"cloud_excluded_pixels":cloud_excluded,
            "classified_pixels":classified_count,"tile_count":plan.count,
            "truncated":truncated,
            "warning":"SCL flags exclude clouds, shadows and ambiguous pixels; "
                      "this is spectral classification, not validated land-cover "
                      "ground truth. Cloud/radiometric quality depends on source."}
