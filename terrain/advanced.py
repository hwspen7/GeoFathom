"""Bounded projected DEM tools for local GIS: contours, cut/fill, D8 and visibility."""
import math
import numpy as np
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform_geom, transform
from shapely.geometry import LineString, MultiLineString, MultiPolygon, box, shape, mapping
from shapely.ops import linemerge
from shapely import make_valid
from geometry.measure import measure_geometry
from imagery.raster import RasterError
from .engine import _check_dem

def _window(path, geometry, maximum):
    measure_geometry(geometry)
    if geometry["type"] not in {"Polygon","MultiPolygon"}:
        raise RasterError("Draw or select a polygon study area.")
    with rasterio.open(path) as source:
        _check_dem(source)
        projected=transform_geom("EPSG:4326",source.crs,geometry)
        boundary=shape(projected)
        try:
            w=from_bounds(*boundary.bounds,transform=source.transform)
            left,top=math.floor(w.col_off),math.floor(w.row_off)
            right,bottom=math.ceil(w.col_off+w.width),math.ceil(w.row_off+w.height)
            w=Window(left,top,right-left,bottom-top).intersection(
                Window(0,0,source.width,source.height))
        except Exception as error:
            raise RasterError("Study area does not overlap the DEM.") from error
        if not(2<=w.width<=maximum and 2<=w.height<=maximum):
            raise RasterError(f"Select a study area of 2–{maximum} pixels on each side.")
        affine=source.window_transform(w)
        z=source.read(1,window=w,masked=True).astype(np.float64)
        covered=geometry_mask([projected],out_shape=z.shape,transform=affine,invert=True)
        values=z.filled(np.nan)
        valid=covered&np.isfinite(values)&~np.ma.getmaskarray(z)
        if not valid.any():raise RasterError("No valid DEM cells in the study area.")
        # Separate source-footprint overlap from cells lost to nodata.
        footprint=box(*source.bounds)
        overlap=boundary.intersection(footprint).area
        coverage=100*overlap/boundary.area if boundary.area>0 else 0.
        return values,valid,covered,affine,source.crs,boundary,min(100.,coverage)

def _feature(g,crs,properties):
    geographic=transform_geom(crs,"EPSG:4326",mapping(g))
    measure_geometry(geographic)
    return {"type":"Feature","geometry":geographic,"properties":properties}

def _collection(features):
    if len(features)>100:
        raise RasterError("Result exceeds 100 features; reduce the study area or contour density.")
    return {"type":"FeatureCollection","features":features}

# Bound actual geometry complexity rather than the number of disconnected
# contour paths. A DEM with many small hills is a normal GIS input.
_CONTOUR_VERTEX_BUDGET=400_000
_CONTOUR_FEATURE_VERTICES=10_000
_CONTOUR_LEVEL_LIMIT=64

def _line_parts(geometry):
    if geometry.geom_type=="LineString":
        if not geometry.is_empty and geometry.length>0:
            yield geometry
    elif geometry.geom_type in {"MultiLineString","GeometryCollection"}:
        for part in geometry.geoms:
            yield from _line_parts(part)

def _contour_groups(lines):
    """Group disconnected lines at one elevation without deleting vertices.

    Split exceptionally long lines at shared endpoints to maintain the
    per-feature geometry budget accepted by the measurement/storage API.
    """
    group=[]
    count=0
    for line in lines:
        coords=list(line.coords)
        for offset in range(0,len(coords)-1,_CONTOUR_FEATURE_VERTICES-1):
            part=coords[offset:offset+_CONTOUR_FEATURE_VERTICES]
            if count+len(part)>_CONTOUR_FEATURE_VERTICES:
                yield group[0] if len(group)==1 else MultiLineString(group)
                group=[];count=0
            group.append(LineString(part));count+=len(part)
    if group:
        yield group[0] if len(group)==1 else MultiLineString(group)

def _contours(z,valid,affine,crs,boundary,interval):
    if not math.isfinite(interval) or interval<=0:
        raise RasterError("Contour interval must be a positive finite number.")
    lo,hi=float(z[valid].min()),float(z[valid].max())
    if hi==lo:return []
    start=math.floor(lo/interval)+1
    end=math.ceil(hi/interval)-1
    if end-start+1>_CONTOUR_LEVEL_LIMIT:
        raise RasterError(f"Choose a larger interval (at most {_CONTOUR_LEVEL_LIMIT} elevation levels, not individual lines).")
    corners=[z[:-1,:-1],z[:-1,1:],z[1:,1:],z[1:,:-1]]
    good=valid[:-1,:-1]&valid[:-1,1:]&valid[1:,1:]&valid[1:,:-1]
    offsets=[(0,0),(1,0),(1,1),(0,1)]
    features=[]
    vertex_count=0
    for n in range(start,end+1):
        level=n*interval
        above=[v>=level for v in corners]
        flags=above[0].astype(np.uint8)+2*above[1]+4*above[2]+8*above[3]
        rows,cols=np.nonzero(good&(flags!=0)&(flags!=15))
        if len(rows)>_CONTOUR_VERTEX_BUDGET:
            raise RasterError("Contour complexity exceeds the geometry budget.")
        segments=[]
        for r,c in zip(rows,cols):
            vals=[v[r,c] for v in corners]
            crossings=[]
            for i in range(4):
                j=(i+1)%4
                if (vals[i]>=level)==(vals[j]>=level):continue
                t=(level-vals[i])/(vals[j]-vals[i])
                x=c+.5+offsets[i][0]+t*(offsets[j][0]-offsets[i][0])
                y=r+.5+offsets[i][1]+t*(offsets[j][1]-offsets[i][1])
                # Canonical rounded grid coordinate joins neighboring cells.
                crossings.append((round(x,10),round(y,10)))
            pairs=[(0,1)] if len(crossings)==2 else (
                [(0,1),(2,3)] if (sum(vals)/4>=level)==(vals[0]>=level)
                else [(0,3),(1,2)])
            for i,j in pairs:
                if crossings[i]!=crossings[j]:
                    segments.append([affine*crossings[i],affine*crossings[j]])
        if not segments:continue
        merged=linemerge(MultiLineString(segments)).intersection(boundary)
        for group in _contour_groups(_line_parts(merged)):
            parts=[group] if group.geom_type=="LineString" else list(group.geoms)
            vertex_count+=sum(len(part.coords) for part in parts)
            if vertex_count>_CONTOUR_VERTEX_BUDGET:
                raise RasterError("Contour geometry exceeds 400,000 vertices; use a larger interval or smaller study area.")
            features.append(_feature(group,crs,{"name":f"Contour {level:g} m","elevation_m":level,
                "major":n%5==0,"contour_path_count":len(parts)}))
    return features

def _origin(point,crs,affine,valid):
    if not isinstance(point,(tuple,list)) or len(point)!=2:
        raise RasterError("Provide observer or outlet longitude and latitude.")
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in point) or not(-180<=point[0]<=180 and -90<=point[1]<=90):
        raise RasterError("Invalid WGS84 observer or outlet.")
    try:
        xx,yy=transform("EPSG:4326",crs,[point[0]],[point[1]])
        if not (math.isfinite(xx[0]) and math.isfinite(yy[0])):
            raise ValueError("Non-finite projected coordinate")
    except Exception as error:
        raise RasterError("Observer/outlet must fall in a valid selected DEM cell.") from error
    c,r=(~affine)*(xx[0],yy[0])
    r,c=math.floor(r),math.floor(c)
    if not(0<=r<valid.shape[0] and 0<=c<valid.shape[1] and valid[r,c]):
        raise RasterError("Observer/outlet must fall in a valid selected DEM cell.")
    return r,c

def _visibility(z,valid,origin,affine,observer_height,target_height):
    if any(not math.isfinite(v) or not 0<=v<=1000 for v in (observer_height,target_height)):
        raise RasterError("Observer and target heights must be 0–1000 meters.")
    if max(z.shape[0]*abs(affine.e),z.shape[1]*abs(affine.a))>10000:
        raise RasterError("Visibility uses a local planar model limited to 10 km.")
    r0,c0=origin
    seen=np.zeros(z.shape,bool);known=np.zeros(z.shape,bool)
    seen[r0,c0]=known[r0,c0]=True
    eye=z[r0,c0]+observer_height
    # Batch rays by integer step count. This preserves the exact nearest-cell
    # ray sampling / nodata semantics while bounding temporary arrays.
    rows,cols=np.nonzero(valid)
    distances=np.maximum(np.abs(rows-r0),np.abs(cols-c0))
    if int(distances.sum())>100_000_000:
        raise RasterError("Visibility exceeds 100 million ray samples; reduce the area or use a coarser DEM.")
    order=np.argsort(distances,kind="stable")
    rows,cols,distances=rows[order],cols[order],distances[order]
    edges=np.flatnonzero(np.r_[True,distances[1:]!=distances[:-1],True])
    for first,last in zip(edges[:-1],edges[1:]):
        steps=int(distances[first])
        if not steps:continue
        fractions=np.arange(1,steps,dtype=np.float64)/steps
        chunk=max(1,min(1024,262144//max(1,steps-1)))
        for start in range(first,last,chunk):
            rr_end=rows[start:min(last,start+chunk)]
            cc_end=cols[start:min(last,start+chunk)]
            rr=np.rint(r0+(rr_end[:,None]-r0)*fractions).astype(np.intp)
            cc=np.rint(c0+(cc_end[:,None]-c0)*fractions).astype(np.intp)
            complete=valid[rr,cc].all(axis=1)
            line=eye+(z[rr_end,cc_end,None]+target_height-eye)*fractions
            known[rr_end,cc_end]=complete
            seen[rr_end,cc_end]=complete&np.all(z[rr,cc]<=line+1e-8,axis=1)
    return seen,known

def _watershed(z,valid,origin,affine):
    """D8 steepest descent, no depression filling; flat/sink cells terminate."""
    height,width=z.shape
    downhill=np.full(z.shape,-1,dtype=np.int64)
    best=np.zeros(z.shape,dtype=np.float64)
    for dr,dc in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
        rs=slice(max(0,-dr),min(height,height-dr));cs=slice(max(0,-dc),min(width,width-dc))
        rt=slice(max(0,dr),min(height,height+dr));ct=slice(max(0,dc),min(width,width+dc))
        slope=(z[rs,cs]-z[rt,ct])/math.hypot(dr*affine.e,dc*affine.a)
        good=valid[rs,cs]&valid[rt,ct]&(slope>best[rs,cs])
        rr,cc=np.indices(slope.shape)
        dest=(rr+rt.start)*width+cc+ct.start
        best[rs,cs][good]=slope[good]
        downhill[rs,cs][good]=dest[good]
    upstream=[[] for _ in range(z.size)]
    for index,dest in enumerate(downhill.flat):
        if dest>=0:upstream[int(dest)].append(index)
    basin=np.zeros(z.size,bool)
    queue=[origin[0]*width+origin[1]]
    basin[queue[0]]=True
    while queue:
        for index in upstream[queue.pop()]:
            if not basin[index]:
                basin[index]=True;queue.append(index)
    return basin.reshape(z.shape)

def _polygon_parts(geometry):
    if geometry.geom_type=="Polygon":
        if not geometry.is_empty:yield geometry
    elif geometry.geom_type in {"MultiPolygon","GeometryCollection"}:
        for part in geometry.geoms:yield from _polygon_parts(part)

def _mask_features(mask,affine,crs,name):
    # Tiled vectorization bounds individual geometry complexity without
    # discarding any true cells. Adjacent chunks share boundaries only.
    output=[];total=0
    for row in range(0,mask.shape[0],64):
        for col in range(0,mask.shape[1],64):
            tile=mask[row:row+64,col:col+64]
            if not tile.any():continue
            local=affine*rasterio.Affine.translation(col,row)
            parts=[];count=0
            def emit():
                if parts:
                    output.append(_feature(parts[0] if len(parts)==1 else MultiPolygon(parts),crs,
                        {"name":name,"source_type":"dem_derived"}))
            for geom,_ in shapes(tile.astype(np.uint8),mask=tile,transform=local,connectivity=4):
                for part in _polygon_parts(make_valid(shape(geom))):
                    points=len(part.exterior.coords)+sum(len(r.coords) for r in part.interiors)
                    if count+points>10000:
                        emit();parts=[];count=0
                    if points>20000:raise RasterError("One mask component exceeds the geometry budget.")
                    total+=points
                    if total>400000:raise RasterError("Mask exceeds 400,000 vertices; use a coarser DEM.")
                    parts.append(part);count+=points
            emit()
    return output

def run_terrain(path,geometry,operation,interval=10.,reference=0.,point=None,observer_height=1.7,target_height=0.):
    if operation not in {"contours","volume","visibility","watershed","mesh"}:
        raise RasterError("Unknown terrain operation.")
    z,valid,covered,affine,crs,boundary,coverage=_window(path,geometry,512 if operation=="visibility" else 1024)
    cell=abs(affine.a*affine.e)
    result={"operation":operation,"source_crs":str(crs),"valid_cells":int(valid.sum()),
        "missing_cells":int((covered&~valid).sum()),"cell_area_m2":cell,"metrics":{},"features":[]}
    if operation=="contours":
        result["features"]=_contours(z,valid,affine,crs,boundary,interval)
        result["metrics"]={"contour_lines":sum(f["properties"]["contour_path_count"] for f in result["features"]),
            "contour_levels":len({f["properties"]["elevation_m"] for f in result["features"]}),
            "interval_m":interval,"minimum_m":float(z[valid].min()),"maximum_m":float(z[valid].max())}
        result["warning"]="Interpolated contours on the source DEM grid; no extrapolation across nodata."
    elif operation=="volume":
        if not math.isfinite(reference):raise RasterError("Reference elevation must be finite.")
        delta=z[valid]-reference
        cut=float(np.maximum(delta,0).sum()*cell)
        fill=float(np.maximum(-delta,0).sum()*cell)
        result["metrics"]={"cut_m3":cut,"fill_m3":fill,"net_cut_m3":cut-fill,
            "covered_grid_area_m2":int(valid.sum())*cell,"reference_elevation_m":reference}
        result["warning"]="Projected cell-center cut/fill estimate versus a horizontal reference plane; nodata excluded, not a certified earthworks survey."
    elif operation=="visibility":
        origin=_origin(point,crs,affine,valid)
        seen,known=_visibility(z,valid,origin,affine,observer_height,target_height)
        result["features"]=_mask_features(seen,affine,crs,"Visible terrain")
        result["metrics"]={"visible_cells":int(seen.sum()),"visible_grid_area_m2":int(seen.sum())*cell,"unknown_cells":int((valid&~known).sum())}
        result["warning"]="Local cell-center terrain visibility; no curvature, refraction, buildings or vegetation. Nodata along rays is unknown."
    elif operation=="watershed":
        origin=_origin(point,crs,affine,valid)
        mask=_watershed(z,valid,origin,affine)
        result["features"]=_mask_features(mask,affine,crs,"D8 contributing area")
        result["metrics"]={"upstream_cells":int(mask.sum()),"upstream_grid_area_m2":int(mask.sum())*cell}
        result["warning"]="D8 contributing area within the selected grid; sinks/flats terminate and external upstream areas are not included."
    else:
        step=max(1,math.ceil(max(z.shape)/64))
        heights=z[::step,::step];mask=valid[::step,::step]
        result["mesh"]={"rows":heights.shape[0],"cols":heights.shape[1],
            "dx_m":abs(affine.a)*step,"dy_m":abs(affine.e)*step,
            "heights":[float(v) if ok else None for v,ok in zip(heights.flat,mask.flat)]}
        result["metrics"]={"minimum_m":float(z[valid].min()),"maximum_m":float(z[valid].max())}
        result["warning"]="Interactive 3D elevation preview sampled from the DEM; gaps represent nodata."
    result["metrics"].update({"dataset_overlap_pct":coverage,
        "valid_grid_pct":100*int(valid.sum())/int(covered.sum())})
    if coverage<99.99:
        result["warning"]+=" Study area extends beyond the DEM footprint; results cover the intersection only."
    if int((covered&~valid).sum()):
        result["warning"]+=" Some covered cells are nodata."
    return result
