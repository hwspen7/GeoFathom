"""Engineering cross sections perpendicular to a projected centerline."""
import math
import numpy as np
import rasterio
from rasterio.warp import transform
from shapely.geometry import LineString
from geometry.measure import measure_geometry
from imagery.raster import RasterError
from .engine import _check_dem
from .cancellation import checkpoint

def cross_sections(path,geometry,spacing,width,cancel=None):
    measure_geometry(geometry)
    if geometry["type"]!="LineString":raise RasterError("Cross sections require a centerline.")
    if not (math.isfinite(spacing) and 1<=spacing<=10000 and math.isfinite(width) and 1<=width<=2000):
        raise RasterError("Station spacing must be 1–10,000 m; section half-width 1–2,000 m.")
    with rasterio.open(path) as src:
        _check_dem(src)
        coords=geometry["coordinates"]
        xs,ys=transform("EPSG:4326",src.crs,[p[0] for p in coords],[p[1] for p in coords])
        line=LineString(zip(xs,ys))
        if line.length<1:raise RasterError("Centerline must exceed one meter.")
        if math.ceil(line.length/spacing)+1>100:raise RasterError("Increase station spacing; limit is 100 sections.")
        stations=list(np.arange(0,line.length,spacing))+[line.length]
        offsets=np.linspace(-width,width,41)
        sections=[];features=[];valid=missing=0
        for station in stations:
            checkpoint(cancel)
            p=line.interpolate(station)
            delta=min(1.,spacing/10,line.length/4)
            a=line.interpolate(max(0.,station-delta));b=line.interpolate(min(line.length,station+delta))
            dx,dy=b.x-a.x,b.y-a.y
            length=math.hypot(dx,dy)
            if length==0:raise RasterError("Undefined centerline direction at a station.")
            # Positive offsets are to the left of centerline travel.
            xx=p.x-offsets*dy/length;yy=p.y+offsets*dx/length
            lon,lat=transform(src.crs,"EPSG:4326",xx.tolist(),yy.tolist())
            samples=[]
            locations=list(zip(xx,yy))
            for off,x,y,(px,py),v in zip(offsets,lon,lat,locations,src.sample(locations,indexes=1,masked=True)):
                row,col=src.index(px,py);raw=v[0]
                inside=0<=row<src.height and 0<=col<src.width
                h=None if not inside or np.ma.is_masked(raw) or not np.isfinite(raw) else float(raw)
                valid+=h is not None;missing+=h is None
                samples.append({"distance_m":float(off+width),"offset_m":float(off),"elevation_m":h,"coordinate":[x,y]})
            sections.append({"station_m":float(station),"length_m":2*width,"samples":samples})
            features.append({"type":"Feature","geometry":{"type":"LineString","coordinates":[[lon[0],lat[0]],[lon[-1],lat[-1]]]},
                "properties":{"name":f"Station {station:.1f} m","station_m":float(station),"color":"#ac642c"}})
        if not valid:raise RasterError("No valid elevations on cross sections.")
        return {"operation":"cross_sections","source_crs":str(src.crs),"valid_cells":valid,"missing_cells":missing,
                "cell_area_m2":abs(src.transform.a*src.transform.e),
                "metrics":{"section_count":len(sections),"centerline_length_m":float(line.length),"section_half_width_m":width},
                "sections":sections,"features":features,
                "warning":"Projected station distance, left-positive offsets, nearest source-cell samples; not survey-grade."}
