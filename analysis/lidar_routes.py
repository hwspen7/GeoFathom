"""Point-cloud research endpoints; horizontal and vertical units are explicit."""
import csv
import hashlib
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pyproj.exceptions import CRSError
from .lidar_science import MAX_BYTES, METHODS, analyze, metric_crs, read_cloud

router = APIRouter(prefix="/analysis/lidar", tags=["3D and LiDAR"])

@router.get("/catalog")
def catalog():
    return {"operations":[{"id":key,"title":value[0],"assumption":value[1]} for key,value in METHODS.items()]}

@router.post("/run")
def run(operation: str, epsg: int, vertical_datum: str = Query(min_length=1,max_length=160),
        k: int = Query(16,ge=3,le=64), size: float = Query(1.,ge=.001,le=1e6),
        radius: float = Query(2.,ge=.001,le=1e6), max_edge: float = Query(10.,ge=.001,le=1e6),
        cloud: UploadFile = File(...), reference: UploadFile | None = File(None)):
    try:
        crs = metric_crs(epsg)
        if not vertical_datum.strip():
            raise ValueError("Specify the common vertical datum or local height reference.")
        p, source = read_cloud(cloud.file.read(MAX_BYTES+1),cloud.filename or "")
        q, ref = read_cloud(reference.file.read(MAX_BYTES+1),reference.filename or "") if reference else (None,None)
        result = analyze(operation,p,q,k=k,size=size,radius=radius,max_edge=max_edge)
        result["receipt"] = {"schema":"geofathom-lidar-1","horizontal_crs":crs,
            "vertical_datum":vertical_datum.strip(),"vertical_unit":"m","crs_assignment":"operator supplied; no reprojection or datum transformation",
            "source":source,"reference":ref,"parameters":{"k":k,"size_m":size,"radius_m":radius,"max_edge_m":max_edge},
            "result_sha256":hashlib.sha256(result["csv"].encode()).hexdigest(),
            "figure_sampling":"evenly spaced result rows, maximum 10000"}
        return result
    except (ValueError,TypeError,OverflowError,UnicodeError,csv.Error,CRSError) as exc:
        raise HTTPException(422,detail=str(exc)) from exc
