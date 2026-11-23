"""Construct independent enclosed areas from a network of shared line segments.

This is explicitly polygonization, not a reinterpretation of an open line as
a polygon. GEOS nodes intersections; projected metric snapping is configurable.
Original source features remain unchanged.
"""
import math
from typing import Any
from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiPoint, shape, mapping
from shapely.ops import transform, unary_union, polygonize_full, snap
from shapely.errors import GEOSException
from .measure import GeometryError, measure_geometry


def polygonize_network(geometries: list[dict[str, Any]], tolerance_m: float = 1.0,
                       minimum_area_m2: float = 0.01, max_faces: int = 300) -> dict:
    if (isinstance(tolerance_m, bool) or not isinstance(tolerance_m, (int,float))
        or not math.isfinite(tolerance_m) or not 0 <= tolerance_m <= 20):
        raise GeometryError("Snap tolerance must be finite, 0–20 meters.")
    if (isinstance(minimum_area_m2, bool) or not isinstance(minimum_area_m2, (int,float))
        or not math.isfinite(minimum_area_m2) or not 0 <= minimum_area_m2 <= 1e10):
        raise GeometryError("Minimum face area must be finite, 0–10 billion m².")
    if not 1 <= max_faces <= 500 or not 1 <= len(geometries) <= 300:
        raise GeometryError("Network requires 1–300 sources and at most 500 faces.")
    lines=[]
    count=0
    for geometry in geometries:
        if not isinstance(geometry, dict) or geometry.get("type") not in (
            "Polygon","MultiPolygon","LineString","MultiLineString","Point"):
            raise GeometryError("Sources must be GeoJSON lines, polygon boundaries or point anchors.")
        try:
            feature=shape(geometry)
            if feature.is_empty: raise GeometryError("Empty source geometry.")
        except (TypeError,ValueError,KeyError,IndexError,GEOSException,OverflowError) as exc:
            raise GeometryError("Invalid source coordinates.") from exc
        # Points alone do not define edges. The user must draw connecting lines.
        if feature.geom_type=="Point":
            if not -180<=feature.x<=180 or not -90<=feature.y<=90:
                raise GeometryError("Point source outside WGS84.")
            continue
        pieces=[feature] if feature.geom_type in ("LineString","Polygon") else list(feature.geoms)
        for piece in pieces:
            boundaries=[piece] if piece.geom_type=="LineString" else [piece.exterior,*piece.interiors]
            for path in boundaries:
                coords=list(path.coords)
                if len(coords)<2: raise GeometryError("Line requires two vertices.")
                for vertex in coords:
                    if (len(vertex)<2 or not all(math.isfinite(v) for v in vertex[:2])
                        or not (-180<=vertex[0]<=180 and -90<=vertex[1]<=90)):
                        raise GeometryError("Finite WGS84 coordinates are required.")
                count+=len(coords)
                if count>20000: raise GeometryError("Network exceeds 20,000 coordinates.")
                lines.append(LineString([p[:2] for p in coords]))
    if not lines: raise GeometryError("Network has no edges.")
    bounds=unary_union(lines).bounds
    west,south,east,north=bounds
    if east-west>45 or north-south>45 or abs((south+north)/2)>=85:
        raise GeometryError("Split large or polar study areas before polygonization.")
    longitude,latitude=(west+east)/2,(south+north)/2
    projected=CRS.from_proj4(
        f"+proj=aeqd +lat_0={latitude:.9f} +lon_0={longitude:.9f} +datum=WGS84 +units=m +no_defs")
    forward=Transformer.from_crs("EPSG:4326",projected,always_xy=True).transform
    backward=Transformer.from_crs(projected,"EPSG:4326",always_xy=True).transform
    paths=[transform(forward,path) for path in lines]
    if tolerance_m>0:
        # Endpoints are included as snapping references for T-junctions.
        # Explicit tolerance avoids silently merging distant separate parcels.
        endpoints=MultiPoint([p for line in paths for p in (line.coords[0],line.coords[-1])])
        paths=[snap(line,endpoints,tolerance_m) for line in paths]
    # Unary union nodes every intersection, even where no original vertex exists.
    graph=unary_union(paths)
    faces,dangles,cuts,invalid=polygonize_full(graph)
    measured=[]
    for face in faces.geoms:
        if face.is_empty or not face.is_valid or face.area<minimum_area_m2: continue
        geographic=mapping(transform(backward,face))
        result=measure_geometry(geographic)  # Ellipsoidal, includes inner rings.
        if result["area_m2"]<minimum_area_m2:continue
        measured.append((face.centroid.y,face.centroid.x,geographic,result))
    if len(measured)>max_faces:
        raise GeometryError(f"Detected {len(measured)} faces; reduce input or increase max_faces.")
    measured.sort(key=lambda x:(-round(x[0],3),round(x[1],3)))
    outputs=[{"id":f"area-{index+1}","name":f"Area {index+1}",
              "geometry":geometry,"measurement":measurement,
              "properties":{"source_type":"polygonized_network",
                            "area_m2":measurement["area_m2"],
                            "perimeter_m":measurement["perimeter_m"],
                            "snap_tolerance_m":tolerance_m}}
             for index,(_,__,geometry,measurement) in enumerate(measured)]
    return {"faces":outputs,"count":len(outputs),
            "area_m2":math.fsum(f["measurement"]["area_m2"] for f in outputs),
            "dangles":len(dangles.geoms),"cuts":len(cuts.geoms),
            "invalid_rings":len(invalid.geoms),"source_segments":len(lines),
            "tolerance_m":tolerance_m,
            "method":"GEOS unary_union + polygonize_full; ellipsoidal WGS84 measurements",
            "warning":"Only genuinely enclosed faces have areas. Dangles/cuts remain as source lines; inspect their diagnostics."}
