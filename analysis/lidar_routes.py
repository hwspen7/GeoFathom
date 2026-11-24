"""Point-cloud research endpoints; horizontal and vertical units are explicit."""
import csv
import hashlib
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pyproj.exceptions import CRSError
from .lidar_science import MAX_BYTES, MAX_POINTS, METHODS, analyze, metric_crs, read_cloud, _serialize
from .lidar_disk import read_compressed, stream_voxels
import io
import numpy as np
from .lidar_exports import raster_grid

router = APIRouter(prefix="/analysis/lidar", tags=["3D and LiDAR"])

@router.get("/catalog")
def catalog():
    return {"operations":[{"id":key,"title":value[0],"assumption":value[1]} for key,value in METHODS.items()]}

@router.post("/run")
def run(operation: str, epsg: int, vertical_datum: str = Query(min_length=1,max_length=160),
        k: int = Query(16,ge=3,le=64), size: float = Query(1.,ge=.001,le=1e6),
        radius: float = Query(2.,ge=.001,le=1e6), max_edge: float = Query(10.,ge=.001,le=1e6),
        trim_fraction: float = Query(.8,ge=.5,le=1), max_iterations: int = Query(60,ge=1,le=100),
        tolerance: float = Query(1e-5,ge=1e-9,le=1), registration_sigma: float = Query(.05,ge=0,le=1e6),
        min_neighbors: int = Query(5,ge=3,le=1000), threshold: float = Query(3.5,ge=0,le=1e6),
        cloud: UploadFile = File(...), reference: UploadFile | None = File(None)):
    try:
        crs = metric_crs(epsg)
        if not vertical_datum.strip():
            raise ValueError("Specify the common vertical datum or local height reference.")
        def load(upload):
            name=upload.filename or ""
            raw=upload.file.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise ValueError("Use streaming voxel statistics for files above 16 MiB.")
            from importlib.util import find_spec
            if name.lower().endswith(".laz") or (name.lower().endswith(".las") and find_spec("laspy") is not None):
                p,meta=read_compressed(io.BytesIO(raw),epsg,MAX_POINTS)
                return p,{**meta,"sha256":hashlib.sha256(raw).hexdigest(),"format":"LAS/LAZ XYZ","points":len(p)}
            return read_cloud(raw,name)
        if operation=="stream_voxels":
            if reference is not None:raise ValueError("Streaming voxel statistics accepts one cloud.")
            if not (cloud.filename or "").lower().endswith((".las",".laz")):raise ValueError("Streaming requires LAS or LAZ.")
            table,metrics=stream_voxels(cloud.file,epsg,size)
            source=metrics.pop("source");ref=None
            columns=["x_m","y_m","z_m","count","min_z_m","max_z_m"]
            data,figure,rows=_serialize(columns,table)
            result={"operation":operation,"columns":columns,"rows":rows,"row_count":len(table),"csv":data,"figure_csv":figure,"metrics":metrics,"assumption":METHODS[operation][1]}
        else:
            p,source=load(cloud)
            q,ref=load(reference) if reference else (None,None)
            result=analyze(operation,p,q,k=k,size=size,radius=radius,max_edge=max_edge,trim_fraction=trim_fraction,max_iterations=max_iterations,
                tolerance=tolerance,registration_sigma=registration_sigma,min_neighbors=min_neighbors,threshold=threshold)
        result["receipt"] = {"schema":"geofathom-lidar-1","horizontal_crs":crs,
            "vertical_datum":vertical_datum.strip(),"vertical_unit":"m","crs_assignment":"operator supplied; no reprojection or datum transformation",
            "source":source,"reference":ref,"parameters":{"k":k,"size_m":size,"radius_m":radius,"max_edge_m":max_edge,"trim_fraction":trim_fraction,"max_iterations":max_iterations,"tolerance_m":tolerance,"registration_sigma_m":registration_sigma,"min_neighbors":min_neighbors,"threshold":threshold},
            "result_sha256":hashlib.sha256(result["csv"].encode()).hexdigest(),
            "figure_sampling":"evenly spaced result rows, maximum 10000"}
        raster_fields={"surface_change":"delta_z_m","correlated_change":"delta_z_m","canopy_structure":"p95_m","canopy_watershed":"canopy_height_m","canopy_complexity":"height_entropy","building_candidates":"height_m"}
        if operation in raster_fields:
            table=np.genfromtxt(io.StringIO(result["csv"]),delimiter=",",skip_header=1,ndmin=2)
            field=raster_fields[operation]
            result["raster_geotiff"]=raster_grid(table,result["columns"],field,size,epsg)
            result["receipt"]["raster_export_field"]=field
            result["receipt"]["raster_export_available"]=result["raster_geotiff"] is not None
        if result.get("mesh_obj"):
            result["receipt"]["mesh_sha256"]=hashlib.sha256(result["mesh_obj"].encode()).hexdigest()
        return result
    except (ValueError,TypeError,OverflowError,UnicodeError,csv.Error,CRSError) as exc:
        raise HTTPException(422,detail=str(exc)) from exc
