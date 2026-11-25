"""Exact project spatial selection with SQLite R-tree candidate pruning.

Rectangular/freehand selection uses a client-supplied valid GeoJSON geometry.
Relations are evaluated on WGS84 topology, with spatial index only as a fast
bounding-box filter. No fuzzy proximity is inferred from degree distances.
"""
from shapely.geometry import shape
from geometry.measure import GeometryError,measure_geometry
from storage.database import StorageError
from storage.paging import bounding_candidates


def select_features(project_id:str,selector:dict,relation:str="intersects",
                    layer_ids:list[str]|None=None,limit:int=200,offset:int=0,
                    visible_only:bool=True)->dict:
    if relation not in {"intersects","within","contains","touches","crosses"}:
        raise StorageError("Unsupported spatial relationship.")
    if not 1<=limit<=500 or not 0<=offset<=100000:
        raise StorageError("Spatial page is out of allowed bounds.")
    measure_geometry(selector)
    area=shape(selector)
    if area.is_empty or not area.is_valid:raise StorageError("Invalid selection geometry.")
    if area.bounds[2]-area.bounds[0]>170:
        raise StorageError("Selection across the antimeridian needs special handling.")
    rows=bounding_candidates(project_id,area.bounds,layer_ids,visible_only,max_candidates=25000)
    results=[]
    for item in rows:
        candidate=shape(item["geometry"])
        # Relation orientation: candidate [relation] selector.
        if getattr(candidate,relation)(area):
            results.append({"id":item["id"],"name":item["name"],
                "layer_id":item["layer_id"],"revision":item["revision"],
                "geometry":item["geometry"],"properties":item["properties"]})
    return {"ids":[x["id"] for x in results[offset:offset+limit]],
            "results":results[offset:offset+limit],
            "total":len(results),"limit":limit,"offset":offset,
            "relation":relation,"method":"SQLite R-tree candidates + Shapely exact predicate"}
