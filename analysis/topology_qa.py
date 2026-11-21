"""Topology QA modeled on common QGIS checks, with explicit AOI semantics.

Diagnose but never silently repair survey geometry. Polygon gap analysis
requires a declared study area, or is restricted to interior union holes.
Area thresholds use WGS84 geodesic square meters, not degrees squared.
"""
from collections import Counter
from itertools import combinations

from pyproj import Geod
from shapely.geometry import shape,mapping,Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from geometry.measure import measure_geometry,GeometryError
from storage.database import StorageError
from storage.paging import bounding_candidates

GEOD=Geod(ellps="WGS84")


def _area(geom):
    return abs(GEOD.geometry_area_perimeter(geom)[0]) if not geom.is_empty else 0.0


def review_topology(project_id:str,layer_ids:list[str]|None=None,
                    study_area:dict|None=None,minimum_area_m2:float=0.01,
                    check_dangles:bool=True,max_issues:int=250)->dict:
    if not 0<=minimum_area_m2<=1_000_000_000:
        raise StorageError("Area tolerance must be between 0 and 1 billion m².")
    if not 1<=max_issues<=1000:raise StorageError("QA issue limit must be 1–1000.")
    if study_area:
        measure_geometry(study_area)
        aoi=shape(study_area)
        if aoi.geom_type not in {"Polygon","MultiPolygon"}:
            raise StorageError("Topology study area must be a polygon.")
        bounds=aoi.bounds
    else:
        aoi=None
        bounds=(-179.9999,-85,179.9999,85)
    items=bounding_candidates(project_id,bounds,layer_ids,False,max_candidates=20000)
    polys=[(row,shape(row["geometry"])) for row in items
           if row["geometry"]["type"] in {"Polygon","MultiPolygon"}]
    lines=[(row,shape(row["geometry"])) for row in items
           if row["geometry"]["type"] in {"LineString","MultiLineString"}]
    problems=[]
    counts=Counter()
    def issue(code,feature_ids,geometry,detail,area=0):
        counts[code]+=1
        if len(problems)>=max_issues:return
        problems.append({"type":code,"feature_ids":feature_ids,
            "geometry":mapping(geometry),"message":detail,"area_m2":area})
    if polys:
        geoms=[geom for _,geom in polys]
        tree=STRtree(geoms)
        for index,(row,geom) in enumerate(polys):
            if not geom.is_valid:
                issue("invalid",[row["id"]],geom,"Invalid polygon geometry")
                continue
            for j in tree.query(geom):
                j=int(j)
                if j<=index:continue
                other_row,other=polys[j]
                if geom.equals(other):
                    issue("duplicate",[row["id"],other_row["id"]],geom,
                          "Duplicate mapped polygon",_area(geom))
                elif geom.intersects(other):
                    overlap=geom.intersection(other)
                    magnitude=_area(overlap)
                    if magnitude>minimum_area_m2:
                        issue("overlap",[row["id"],other_row["id"]],overlap,
                              "Polygon areas overlap",magnitude)
        combined=unary_union(geoms)
        if aoi is not None:
            holes=aoi.difference(combined)
        else:
            shell=unary_union([Polygon(part.exterior)
                for part in (list(combined.geoms) if combined.geom_type=="MultiPolygon"
                             else [combined]) if isinstance(part,Polygon)])
            holes=shell.difference(combined)
        if not holes.is_empty:
            for gap in (list(holes.geoms) if hasattr(holes,"geoms") else [holes]):
                if gap.geom_type!="Polygon":continue
                magnitude=_area(gap)
                if magnitude>minimum_area_m2:
                    issue("gap",[],gap,"Uncovered area in the chosen topology study area" if aoi
                          else "Internal polygon hole in the mapped coverage",magnitude)
    if check_dangles:
        # Report line endpoints that have no second line endpoint within
        # ~1 cm at the equator. These may be legitimate road dead ends.
        endpoints=[]
        for row,line in lines:
            for part in (line.geoms if line.geom_type=="MultiLineString" else [line]):
                endpoints.extend([(row["id"],tuple(part.coords[0])),
                                  (row["id"],tuple(part.coords[-1]))])
        counts_at=Counter((round(p[0],7),round(p[1],7)) for _,p in endpoints)
        for uid,p in endpoints:
            if counts_at[(round(p[0],7),round(p[1],7))]==1:
                from shapely.geometry import Point
                issue("dangle",[uid],Point(p),"Potential disconnected line endpoint")
    return {"issues":problems,"counts":dict(counts),"checked_features":len(items),
            "issue_count":sum(counts.values()),"truncated":sum(counts.values())>len(problems),
            "method":"Shapely STRtree topology; WGS84 geodesic area",
            "warning":"Dangles can be legitimate. Without an AOI, exterior gaps are not inferred."}
