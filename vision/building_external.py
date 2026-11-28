"""Native-grid contracts for operator-local pretrained building candidates.

External repositories execute only in explicitly invoked local research tools,
never in an API request or production inference worker.
"""
import json
from pathlib import Path
import subprocess

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import Polygon,box
from shapely.ops import unary_union

from imagery.store import file_sha256
from imagery.raster import RasterError
from .building_dataset import canonical_sha

CATALOG={
    "unibuild":{"repository":"https://github.com/zhu-xlab/UniBuild.git",
                "revision":"cfbbdf5682cb435000a19fe7f3f66c3cc341ccc6",
                "code_license":"not declared in pinned repository",
                "kind":"probability","checkpoint":"unibuild_dinov3_base_hrdpt.pth"},
    "sampolybuild":{"repository":"https://github.com/wchh-2000/SAMPolyBuild.git",
                    "revision":"0edf90e3deb5170c141f396db0c77fa5c3295860",
                    "code_license":"Apache-2.0","kind":"instances","checkpoint":"auto_whumix.pth"},
    "pix2poly":{"repository":"https://github.com/yeshwanth95/Pix2Poly.git",
                "revision":"4e4c00359b41f31fe80f7fbdab0fa50eb7a46ab8",
                "code_license":"MIT","kind":"instances","checkpoint":"operator-selected INRIA checkpoint"},
}


def upstream_identity(name,root,checkpoint,*,authorized=False):
    if name not in CATALOG or not authorized:
        raise RasterError("Explicitly confirm authorization to use upstream code and weights.")
    root=Path(root).resolve();checkpoint=Path(checkpoint).resolve()
    def git(*args):
        return subprocess.run(["git","-C",str(root),*args],check=True,
                              capture_output=True,text=True,timeout=30).stdout.strip()
    info=CATALOG[name]
    if git("rev-parse","HEAD")!=info["revision"] or git("status","--porcelain","--untracked-files=all"):
        raise RasterError("Use the pinned, clean upstream checkout; store weights outside it.")
    if not checkpoint.is_file() or not 0<checkpoint.stat().st_size<=8*1024**3:
        raise RasterError("Choose an existing authorized checkpoint under 8 GiB.")
    return {"name":name,"revision":info["revision"],"repository":info["repository"],
            "code_license":info["code_license"],"checkpoint_sha256":file_sha256(checkpoint)}


def source_rgb(path):
    with rasterio.open(path) as src:
        if min(src.shape)<1 or max(src.shape)>2048 or src.count<3:
            raise RasterError("External research supports bounded RGB chips up to 2048 pixels per axis.")
        data=src.read([1,2,3],masked=True)
        if np.ma.getmaskarray(data).any() or not np.isfinite(data.data).all() or np.any((data.data<0)|(data.data>255)):
            raise RasterError("External candidates require fully observed 0-255 RGB inputs.")
        if any(dtype!="uint8" for dtype in src.dtypes[:3]):
            raise RasterError("External RGB chips must be uint8; no hidden quantization.")
        return np.moveaxis(data.data,0,-1)


def windows(shape,size,stride):
    if not 1<=stride<=size:
        raise ValueError("Invalid tile stride.")
    def starts(n):
        return sorted(set([*range(0,max(1,n-size+1),stride),max(0,n-size)]))
    return [(y,x,min(size,shape[0]-y),min(size,shape[1]-x))
            for y in starts(shape[0]) for x in starts(shape[1])]


def coco_polygons(rows,image_id):
    """COCO rings are exterior parts, not holes. Never infer hole topology."""
    result=[]
    if not isinstance(rows,list):
        raise RasterError("Expected a COCO prediction list.")
    for row in rows:
        if str(row.get("image_id"))!=str(image_id):
            raise RasterError("Prediction image identity does not match the source.")
        score=float(row.get("score",1.))
        if not np.isfinite(score) or not 0<=score<=1:
            raise RasterError("Invalid instance score.")
        segments=row.get("segmentation")
        if not isinstance(segments,list):
            raise RasterError("Expected polygon rings rather than compressed masks.")
        result.append({"rings":segments,"score":score})
    return result


def native_instances(records,shape,*,minimum_pixels=9,max_objects=20000):
    """Confidence-ordered nonoverlapping pixel ownership; report all conflicts.

    Keep the original polygon candidates as research evidence. Invalid geometry
    is counted and excluded rather than silently repaired.
    """
    h,w=shape
    if len(records)>max_objects:
        raise RasterError("External instance count exceeds the explicit allowance.")
    canvas=box(0,0,w,h)
    objects=[];invalid=0;clipped=0
    for i,r in enumerate(records):
        score=float(r.get("score",1.))
        if not np.isfinite(score) or not 0<=score<=1:
            raise RasterError("Invalid instance score.")
        parts=[]
        for ring in r["rings"]:
            points=np.asarray(ring,np.float64)
            if points.size<6 or points.size%2 or not np.isfinite(points).all():
                invalid+=1;continue
            poly=Polygon(points.reshape(-1,2))
            if not poly.is_valid or poly.is_empty or poly.area<=0:
                invalid+=1;continue
            if not canvas.covers(poly):
                clipped+=1
            poly=poly.intersection(canvas)
            if not poly.is_empty and poly.area>0:
                parts.append(poly)
        if parts:
            geom=unary_union(parts)
            if geom.is_valid and geom.area>0:
                objects.append((score,i,geom))
    ids=np.zeros(shape,np.int32);overlap=0;discarded=0;accepted=[]
    for score,i,geom in sorted(objects,key=lambda a:(-a[0],a[1])):
        x0,y0,x1,y1=geom.bounds
        x0=max(0,int(np.floor(x0)));y0=max(0,int(np.floor(y0)))
        x1=min(w,int(np.ceil(x1)));y1=min(h,int(np.ceil(y1)))
        if x1<=x0 or y1<=y0:
            discarded+=1;continue
        region=ids[y0:y1,x0:x1]
        support=rasterize([(geom,1)],out_shape=region.shape,transform=Affine.translation(x0,y0),dtype="uint8").astype(bool)
        overlap+=int((support&(region>0)).sum())
        owned=support&(region==0)
        if int(owned.sum())<minimum_pixels:
            discarded+=1;continue
        region[owned]=len(accepted)+1
        accepted.append({"source_index":i,"score":score,"pixels":int(owned.sum())})
    return ids,{"input_candidates":len(records),"accepted":len(accepted),"invalid_rings":invalid,
                "clipped_rings":clipped,"overlap_pixels_counted_with_multiplicity":overlap,
                "discarded_small_or_occluded":discarded,"instances":accepted}


def polygon_fields(ids,valid):
    if ids.shape!=valid.shape or np.any((ids>0)&~valid):
        raise RasterError("Instance predictions exceed valid support.")
    # Binary indicator is NOT a calibrated probability; consumers suppress
    # probability-calibration comparisons for these models.
    return {"probability":np.where(valid,ids>0,-1).astype(np.float32),"valid":valid}


def write_prediction(directory,source,name,payload,identity,settings):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    with rasterio.open(source) as src:
        shape=src.shape
    if name=="unibuild":
        p=np.asarray(payload,np.float32)
        if p.shape!=shape or not np.isfinite(p).all() or np.any((p<0)|(p>1)):
            raise RasterError("External probability raster is invalid.")
        path=directory/"probability.npy";np.save(path,p)
        diagnostic=None
    else:
        ids,diagnostic=native_instances(payload,shape)
        path=directory/"instances.npy";np.save(path,ids)
        (directory/"polygons.json").write_text(json.dumps(payload,allow_nan=False),encoding="utf-8")
    manifest={"model":identity,"settings":settings,"source_sha256":file_sha256(Path(source)),
              "shape":list(shape),"data":path.name,"data_sha256":file_sha256(path),
              "diagnostics":diagnostic,"polygon_sha256":file_sha256(directory/"polygons.json") if diagnostic is not None else None}
    manifest["sha256"]=canonical_sha(manifest)
    (directory/"prediction.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return manifest


def read_prediction(directory,source,name):
    directory=Path(directory)
    m=json.loads((directory/"prediction.json").read_text(encoding="utf-8"))
    expected="probability.npy" if name=="unibuild" else "instances.npy"
    if (name not in CATALOG or m.get("model",{}).get("name")!=name
            or m["model"].get("revision")!=CATALOG[name]["revision"]
            or m.get("data")!=expected or m.get("sha256")!=canonical_sha({k:v for k,v in m.items() if k!="sha256"})
            or m.get("source_sha256")!=file_sha256(Path(source))
            or m.get("data_sha256")!=file_sha256(directory/expected)):
        raise RasterError("External prediction provenance or bytes do not match.")
    with rasterio.open(source) as src:
        shape=src.shape
        valid=(src.read_masks([1,2,3])>0).all(0)
    value=np.load(directory/expected,allow_pickle=False)
    if value.shape!=shape or list(shape)!=m["shape"] or not valid.all():
        raise RasterError("External predictions require fully valid aligned native grids.")
    if name=="unibuild":
        if value.dtype!=np.float32 or not np.isfinite(value).all() or np.any((value<0)|(value>1)):
            raise RasterError("Invalid probability artifact.")
        return {"probability":value,"valid":valid},None,m
    if (value.dtype!=np.int32 or np.any(value<0) or int(value.max())>20000
            or m.get("polygon_sha256")!=file_sha256(directory/"polygons.json")):
        raise RasterError("Invalid native instance artifact.")
    return polygon_fields(value,valid),value,m
