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
from .cancellation import checkpoint
from .vertical import vertical_datum
from .professional import SURFACES, surface, d8_directions, D8, raster_product
from .catalog import ADVANCED_OPERATIONS
from .hydrology import condition_dem

def _window(path, geometry, maximum, max_cells=1_000_000):
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
        if not(2<=w.width<=maximum and 2<=w.height<=maximum and w.width*w.height<=max_cells):
            raise RasterError(f"This terrain operation supports up to {max_cells:,} pixels and {maximum} pixels on each side. Choose a coarser DEM or a smaller study area.")
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

def _contours(z,valid,affine,crs,boundary,interval,cancel=None):
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
        checkpoint(cancel)
        level=n*interval
        above=[v>=level for v in corners]
        flags=above[0].astype(np.uint8)+2*above[1]+4*above[2]+8*above[3]
        rows,cols=np.nonzero(good&(flags!=0)&(flags!=15))
        if len(rows)>_CONTOUR_VERTEX_BUDGET:
            raise RasterError("Contour complexity exceeds the geometry budget.")
        segments=[]
        for index,(r,c) in enumerate(zip(rows,cols)):
            if index%1024==0:checkpoint(cancel)
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

def _visibility(z,valid,origin,affine,observer_height,target_height,cancel=None,
                consider_curvature=False,refraction_coeff=0.13,
                max_distance_m=0.,view_azimuth=0.,view_width=360.):
    if any(not math.isfinite(v) or not 0<=v<=1000 for v in (observer_height,target_height)):
        raise RasterError("Observer and target heights must be 0–1000 meters.")
    if consider_curvature and not (math.isfinite(refraction_coeff) and 0 <= refraction_coeff <= .5):
        raise RasterError("Atmospheric refraction coefficient must be between 0 and 0.5.")
    if max(z.shape[0]*abs(affine.e),z.shape[1]*abs(affine.a))>10000:
        raise RasterError("Visibility analysis is limited to a 10 km local extent.")
    # Effective-Earth-radius correction lowers ray samples relative to the
    # observer tangent; no correction is written to the source DEM.
    curvature=(1-refraction_coeff)/(2*6371008.8) if consider_curvature else 0.0
    dx_m,dy_m=abs(affine.a),abs(affine.e)
    r0,c0=origin
    seen=np.zeros(z.shape,bool);known=np.zeros(z.shape,bool)
    seen[r0,c0]=known[r0,c0]=True
    eye=z[r0,c0]+observer_height
    # Batch rays by integer step count. This preserves the exact nearest-cell
    # ray sampling / nodata semantics while bounding temporary arrays.
    rows,cols=np.nonzero(valid)
    # Azimuth is clockwise from grid north. Pixels outside the requested
    # sector are known to be outside the observation model, not NoData rays.
    included=np.ones(rows.shape,bool)
    if max_distance_m>0:
        included &= np.hypot((rows-r0)*dy_m,(cols-c0)*dx_m)<=max_distance_m+1e-9
    if view_width<360:
        bearing=(np.degrees(np.arctan2((cols-c0)*dx_m,(r0-rows)*dy_m))+360)%360
        delta=(bearing-view_azimuth+180)%360-180
        included &= np.abs(delta)<=view_width/2+1e-10
    known[rows[~included],cols[~included]]=True
    rows,cols=rows[included],cols[included]
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
            checkpoint(cancel)
            rr_end=rows[start:min(last,start+chunk)]
            cc_end=cols[start:min(last,start+chunk)]
            rr=np.rint(r0+(rr_end[:,None]-r0)*fractions).astype(np.intp)
            cc=np.rint(c0+(cc_end[:,None]-c0)*fractions).astype(np.intp)
            complete=valid[rr,cc].all(axis=1)
            distance_sq=((rr_end-r0)*dy_m)**2+((cc_end-c0)*dx_m)**2
            target_z=z[rr_end,cc_end]-curvature*distance_sq+target_height
            line=eye+(target_z[:,None]-eye)*fractions
            blockers=z[rr,cc]-curvature*distance_sq[:,None]*fractions[None,:]**2
            known[rr_end,cc_end]=complete
            seen[rr_end,cc_end]=complete&np.all(blockers<=line+1e-8,axis=1)
    return seen,known

def _watershed(z,valid,origin,affine,cancel=None):
    """D8 steepest descent, no depression filling; flat/sink cells terminate."""
    height,width=z.shape
    downhill,_=d8_directions(z,valid,abs(affine.a),abs(affine.e),cancel)
    basin=np.zeros(z.shape,bool);basin[origin]=True
    queue=[origin]
    # Traverse reverse D8 edges directly instead of allocating one list per cell.
    while queue:
        checkpoint(cancel)
        r,c=queue.pop()
        for dr,dc,_ in D8:
            rr,cc=r+dr,c+dc
            if 0<=rr<height and 0<=cc<width and not basin[rr,cc] and downhill[rr,cc]==r*width+c:
                basin[rr,cc]=True;queue.append((rr,cc))
    return basin

def _polygon_parts(geometry):
    if geometry.geom_type=="Polygon":
        if not geometry.is_empty:yield geometry
    elif geometry.geom_type in {"MultiPolygon","GeometryCollection"}:
        for part in geometry.geoms:yield from _polygon_parts(part)

def _mask_features(mask,affine,crs,name,cancel=None):
    # Tiled vectorization bounds individual geometry complexity without
    # discarding any true cells. Adjacent chunks share boundaries only.
    output=[];total=0
    for row in range(0,mask.shape[0],64):
        for col in range(0,mask.shape[1],64):
            checkpoint(cancel)
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

def run_terrain(path,geometry,operation,interval=10.,reference=0.,point=None,observer_height=1.7,target_height=0.,
                end_point=None,max_slope=30.,min_elevation=-12000.,max_elevation=12000.,max_tri=100.,
                stream_cells=100,azimuth=315.,altitude=45.,section_spacing=50.,section_width=20.,texture_path=None,
                fill_sinks=False,consider_curvature=False,refraction_coeff=0.13,comparison_path=None,observer_points=None,gradient_method="horn",slope_classes="standard",mfd_exponent=1.1,neighborhood_radius=1,
                max_distance_m=0.,view_azimuth=0.,view_width=360.,
                route_model="surface",mesh_samples=256,cancel=None):
    checkpoint(cancel)
    if gradient_method not in {"horn","zevenbergen_thorne"}:
        raise RasterError("Unsupported terrain gradient method.")
    if slope_classes not in {"standard","detailed","broad"}:
        raise RasterError("Unsupported slope classification preset.")
    if not math.isfinite(mfd_exponent) or not .5<=mfd_exponent<=8:
        raise RasterError("MFD exponent must be between 0.5 and 8.")
    if neighborhood_radius not in (1,2,3,4):
        raise RasterError("Neighborhood radius must be 1–4 cells.")
    if not math.isfinite(max_distance_m) or not 0<=max_distance_m<=10000:
        raise RasterError("Viewshed range must be 0–10,000 meters.")
    if not math.isfinite(view_azimuth) or not 0<=view_azimuth<=360:
        raise RasterError("Viewshed azimuth must be 0–360 degrees.")
    if not math.isfinite(view_width) or not 0<view_width<=360:
        raise RasterError("Viewshed width must be in (0, 360] degrees.")
    if route_model not in {"surface","distance","gentle"}:
        raise RasterError("Unsupported route cost model.")
    if not isinstance(mesh_samples,int) or not 64<=mesh_samples<=512:
        raise RasterError("3D mesh budget must be 64–512 samples per axis.")
    if operation=="cross_sections":
        from .corridor import cross_sections
        return cross_sections(path,geometry,section_spacing,section_width,cancel)
    if operation not in ADVANCED_OPERATIONS:
        raise RasterError("Unknown terrain operation.")
    # Independent analysis budgets. Local surface derivatives can use large
    # grids; visibility ray tracing and catchment/path traversals remain bounded.
    simple_large={"dem_difference","elevation","slope_map","aspect_map","hillshade","tri","tpi",
                  "curvature","plan_curvature","profile_curvature","cutfill_map","suitability","volume","distribution"}
    extended=operation in simple_large
    maximum=4096 if extended else 512 if operation in {"visibility","viewshed_multi"} else 1024
    max_cells=8_000_000 if extended else 262_144 if operation in {"visibility","viewshed_multi"} else 1_000_000
    z,valid,covered,affine,crs,boundary,coverage=_window(path,geometry,maximum,max_cells)
    # Read declared vertical datum metadata independently of numerical
    # heights. Missing metadata remains unknown; never invent NAVD88/EGM96.
    with rasterio.open(path) as source:
        source_datum=vertical_datum(source)
    checkpoint(cancel)
    hydro_ops={"flow_direction","flow_accumulation","flow_accumulation_mfd",
               "streams","stream_order","watershed"}
    # Drainage may use a conditioned working grid; other surface products
    # always operate on the original elevations.
    flow_z,conditioned=(condition_dem(z,valid,cancel) if fill_sinks and operation in hydro_ops
                        else (z,None))
    cell=abs(affine.a*affine.e)
    result={"operation":operation,"source_crs":str(crs),
        "algorithm_options":{"gradient_method":gradient_method,"slope_classes":slope_classes,
                             "mfd_exponent":mfd_exponent if operation=="flow_accumulation_mfd" else None,
                             "neighborhood_radius_cells":neighborhood_radius if operation in {"tri","tpi"} else None,
                             "route_model":route_model if operation=="least_cost" else None,
                             "mesh_samples":mesh_samples if operation=="mesh" else None,
                             "maximum_distance_m":max_distance_m if operation in {"visibility","viewshed_multi"} else None,
                             "view_azimuth_deg":view_azimuth if operation in {"visibility","viewshed_multi"} else None,
                             "view_width_deg":view_width if operation in {"visibility","viewshed_multi"} else None},"valid_cells":int(valid.sum()),
        "missing_cells":int((covered&~valid).sum()),"cell_area_m2":cell,
        "source_vertical_datum":source_datum,"metrics":{},"features":[]}
    if operation in SURFACES:
        result["raster"],result["metrics"],result["features"]=surface(flow_z,valid,affine,crs,operation,reference,point,end_point,
            max_slope,min_elevation,max_elevation,max_tri,stream_cells,azimuth,altitude,
            _feature,_origin,cancel,source_datum=source_datum,
            gradient_method=gradient_method,slope_classes=slope_classes,mfd_exponent=mfd_exponent,
            neighborhood_radius=neighborhood_radius,route_model=route_model)
        result["warning"]="Projected source-grid product; nodata and incomplete neighborhoods excluded. Unconditioned D8 terminates at sinks/flats; suitability and path costs are screening estimates, not engineering certification."
        if operation=="flow_accumulation_mfd":
            result["warning"]=(
                f"Freeman-style MFD slope-power routing (exponent {mfd_exponent:g}) "
                "in fractional cell equivalents on a projected grid; "
                "flats and sinks terminate unless conditioning is enabled. "
                "NoData cannot be a flow receiver; this is screening hydrology.")
        elif operation=="stream_order":
            result["warning"]=(
                "Strahler stream orders on the thresholded D8 channel network. "
                "Unknown upstream regions outside the selected DEM are excluded; "
                "orders are screening estimates, not a surveyed stream inventory.")
        if operation=="streams" and result["metrics"]["drainage_edges"]>result["metrics"]["vector_edges"]:
            result["warning"]+=" Vector edge budget exceeded; full drainage raster remains available."
    elif operation=="dem_difference":
        from .difference import compare_dem
        result["raster"],result["metrics"]=compare_dem(z,valid,affine,crs,comparison_path,cancel,primary_path=path)
        result["warning"]=("Primary minus comparison DEM, bilinearly aligned on the primary grid. "
                           "Declared vertical datum labels agree but have not been independently verified. "
                           if result["metrics"]["datum_labels_match"] else
                           "Primary minus comparison DEM, bilinearly aligned on the primary grid. "
                           "At least one vertical datum label is missing: change estimates are unverified. ")
        # Difference volumes are only meaningful over the intersection:
        # make partial reference coverage explicit in the scientific result.
        overlap=result["metrics"]["comparison_coverage_pct"]
        if overlap<99.9:
            result["warning"]+=(
                f" Only {overlap:.1f}% of valid primary grid cells have matching "
                "reference elevations; differences and volumes exclude uncovered cells.")
    elif operation=="contours":
        result["features"]=_contours(z,valid,affine,crs,boundary,interval,cancel)
        result["metrics"]={"contour_lines":sum(f["properties"]["contour_path_count"] for f in result["features"]),
            "contour_levels":len({f["properties"]["elevation_m"] for f in result["features"]}),
            "interval_m":interval,"minimum_m":float(z[valid].min()),"maximum_m":float(z[valid].max())}
        result["warning"]="Interpolated contours on the source DEM grid; no extrapolation across nodata."
    elif operation=="distribution":
        # Use every valid source cell rather than the subsampled display mesh.
        elevations=z[valid]
        lo,hi=float(elevations.min()),float(elevations.max())
        p10,median,p90=(float(v) for v in np.percentile(elevations,[10,50,90]))
        if lo==hi:
            counts=np.array([elevations.size])
            edges=np.array([lo,hi])
        else:
            counts,edges=np.histogram(elevations,bins=20,range=(lo,hi))
        cumulative=np.cumsum(counts)
        result["distribution"]=[
            {"lower_m":float(edges[i]),"upper_m":float(edges[i+1]),
             "cells":int(count),"area_m2":int(count)*cell,
             "cumulative_pct":100*int(cumulative[i])/elevations.size}
            for i,count in enumerate(counts)]
        mean=float(elevations.mean())
        result["metrics"]={"minimum_m":lo,"maximum_m":hi,"mean_m":mean,
            "median_m":median,"stddev_m":float(elevations.std()),
            "p10_m":p10,"p90_m":p90,"relief_m":hi-lo,
            "covered_grid_area_m2":int(valid.sum())*cell}
        if hi>lo:
            result["metrics"]["hypsometric_integral"]=(mean-lo)/(hi-lo)
        result["warning"]="Cell-center elevation distribution on the valid projected DEM grid; nodata excluded. Cumulative area includes elevations through each bin."
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
        seen,known=_visibility(z,valid,origin,affine,observer_height,target_height,cancel,
                               consider_curvature,refraction_coeff,max_distance_m,view_azimuth,view_width)
        result["features"]=_mask_features(seen,affine,crs,"Visible terrain",cancel)
        result["metrics"]={"visible_cells":int(seen.sum()),"visible_grid_area_m2":int(seen.sum())*cell,"unknown_cells":int((valid&~known).sum()),
            "maximum_distance_m":max_distance_m,"view_azimuth_deg":view_azimuth,
            "view_width_deg":view_width}
        result["warning"]=("Local cell-center visibility with Earth curvature and configurable atmospheric refraction. "
                           if consider_curvature else "Local planar cell-center visibility; curvature and refraction disabled. ")+"Buildings/vegetation depend on the input DEM/DSM; NoData along rays is unknown."
    elif operation=="viewshed_multi":
        # A count raster preserves observer overlap, not merely the union
        # polygon. Unknown rays stay NoData rather than becoming invisible.
        if point is not None:
            raise RasterError("Use observer_points, not point, for multi-observer visibility.")
        if not isinstance(observer_points,(list,tuple)) or not 2<=len(observer_points)<=4:
            raise RasterError("Multi-observer visibility requires 2–4 observer points.")
        origins=[_origin(observer,crs,affine,valid) for observer in observer_points]
        if len(set(origins))!=len(origins):
            raise RasterError("Multi-observer points must occupy distinct DEM cells.")
        rows,cols=np.nonzero(valid)
        # Preflight total ray steps across all observers before tracing any.
        total_steps=sum(
            int(np.maximum(np.abs(rows-r),np.abs(cols-c)).sum())
            for r,c in origins)
        if total_steps>100_000_000:
            raise RasterError("Multi-observer visibility exceeds 100 million ray samples; reduce the area.")
        count=np.zeros(z.shape,dtype=np.uint8)
        fully_known=valid.copy()
        for origin in origins:
            checkpoint(cancel)
            visible,available=_visibility(z,valid,origin,affine,
                observer_height,target_height,cancel,consider_curvature,
                refraction_coeff,max_distance_m,view_azimuth,view_width)
            count+=visible.astype(np.uint8)
            # A count of zero or one is not exact if ANY observer's ray
            # crosses NoData. Mark such pixels unknown rather than
            # misrepresenting a partial count as total observer coverage.
            fully_known &= available
        union=count>0
        # Chart categories must be mutually exclusive. Partial but positive
        # sightings remain available as vector geometry, while the strict
        # raster/count metrics refer only to pixels known for ALL observers.
        fully_visible=union&fully_known
        result["raster"]=raster_product(
            np.where(fully_known,count.astype(float),np.nan),
            "viewshed_multi",affine,crs,cancel,source_datum=source_datum)
        result["features"]=_mask_features(union,affine,crs,
                                          "Visible from any observer",cancel)
        result["metrics"]={
            "observer_count":len(origins),
            "visible_cells":int(fully_visible.sum()),
            "visible_any_known_cells":int(union.sum()),
            "visible_by_all_cells":int((count==len(origins)).sum()),
            "visible_grid_area_m2":int(fully_visible.sum())*cell,
            "unknown_cells":int((valid&~fully_known).sum()),
            "maximum_distance_m":max_distance_m,"view_azimuth_deg":view_azimuth,
            "view_width_deg":view_width,
        }
        result["warning"]=(
            "Multi-observer cell-center viewshed: raster values count the "
            "observers with unobstructed sightlines only when all observer "
            "rays are known; NoData means one or more rays are unknown. "
            "The vector union includes any positively observed cells even "
            "when other observer rays are unknown. "
            "Terrain/DSM only, without independently verified buildings.")
    elif operation=="watershed":
        origin=_origin(point,crs,affine,valid)
        mask=_watershed(flow_z,valid,origin,affine,cancel)
        result["features"]=_mask_features(mask,affine,crs,"D8 contributing area",cancel)
        result["metrics"]={"upstream_cells":int(mask.sum()),"upstream_grid_area_m2":int(mask.sum())*cell}
        result["warning"]=("D8 contributing area within the selected grid; the working DEM was depression-filled and flat cells routed. "
                           if conditioned is not None else
                           "D8 contributing area within the selected grid; unconditioned sinks and flats terminate. "
                           )+"External upstream areas are never included."
    else:
        # Interactive WebGL2 preview: preserve up to 256 samples per axis.
        # Original source DEM and raster exports are never downsampled here.
        step=max(1,math.ceil(max(z.shape)/mesh_samples))
        heights=z[::step,::step];mask=valid[::step,::step]
        first=mask[:-1,:-1]&mask[1:,:-1]&mask[:-1,1:]
        second=mask[:-1,1:]&mask[1:,:-1]&mask[1:,1:]
        if not (first.any() or second.any()):raise RasterError("No complete terrain mesh triangle in the sampled grid.")
        result["mesh"]={"rows":heights.shape[0],"cols":heights.shape[1],
            "origin_xy":list(affine*(.5,.5)),"source_crs":str(crs),
            "dx_m":abs(affine.a)*step,"dy_m":abs(affine.e)*step,
            "heights":[float(v) if ok else None for v,ok in zip(heights.flat,mask.flat)]}
        if texture_path is not None:
            from .texture import mesh_texture
            result["mesh"]["texture"]=mesh_texture(texture_path,affine,crs,heights.shape[0],heights.shape[1],step,cancel)
        result["metrics"]={"minimum_m":float(z[valid].min()),"maximum_m":float(z[valid].max()),
            "mesh_vertices":int(mask.sum()),"mesh_sampling_step":int(step),
            "mesh_grid_coverage_pct":100*float(mask.sum())/max(1,mask.size)}
        result["warning"]="Interactive 3D elevation preview sampled from the DEM; gaps represent nodata."
    if conditioned is not None:
        result["metrics"].update(conditioned)
        result["metrics"]["conditioning_fill_volume_m3"]=conditioned["total_fill_depth_m"]*cell
        result["warning"]+=" Priority-flood depression filling and flat routing applied to a working surface; NoData boundaries are outlets."
    result["metrics"].update({"dataset_overlap_pct":coverage,
        "valid_grid_pct":100*int(valid.sum())/int(covered.sum())})
    if coverage<99.99:
        result["warning"]+=" Study area extends beyond the DEM footprint; results cover the intersection only."
    if int((covered&~valid).sum()):
        result["warning"]+=" Some covered cells are nodata."
    # Explicit, machine-readable scientific boundaries for each result.
    # Passing a test fixture is not equivalent to independent field accuracy.
    flags=[]
    if coverage < 99.99:flags.append("partial_source_overlap")
    if result["missing_cells"]:flags.append("nodata_within_study")
    if not source_datum:flags.append("vertical_datum_unreported")
    if operation in {"watershed","flow_accumulation","flow_accumulation_mfd","streams","stream_order"}:
        flags.append("upstream_outside_grid_not_evaluated")
    result["quality"]={
        "status":"provisional_not_independently_verified",
        "reference_validation":"not_performed",
        "uncertainty":"not_quantified",
        "source_overlap_pct":float(coverage),
        "valid_study_cell_pct":float(result["metrics"]["valid_grid_pct"]),
        "derivative_coverage_pct":float(100*result["raster"]["valid_cells"]/max(1,result["valid_cells"])) if "raster" in result else None,
        "flags":flags,
        "area_basis":"planar_projected_grid_cells"
    }
    checkpoint(cancel)
    return result
