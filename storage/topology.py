"""Topological shared-vertex edits applied to adjacent project features.

Only geometries containing a vertex within an explicit meter tolerance of the
chosen old point are touched. This is NOT an automatic boundary conflation
engine: segments with dissimilar node positions need matching first.
"""

import json
import math

from pyproj import Geod

from geometry.editing import coordinate
from geometry.measure import GeometryError, measure_geometry
from .database import StorageError, _connect, _now, _required_project
from .workspace import _schema, _feature_layer, _revision

_GEOD=Geod(ellps="WGS84")


def _replace_vertices(source, old, new, tolerance_m):
    changed=0
    def recurse(value):
        nonlocal changed
        if (isinstance(value, list) and len(value)>=2
                and isinstance(value[0],(int,float))
                and isinstance(value[1],(int,float))):
            _,_,distance=_GEOD.inv(value[0],value[1],*old)
            if distance <= tolerance_m:
                changed+=1
                return [new[0],new[1],*value[2:]]
            return list(value)
        return [recurse(child) for child in value]
    result={**source,"coordinates":recurse(source["coordinates"])}
    # Closed polygon rings need identical first/last positions; update both.
    return result,changed


def preview_shared_vertex(project_id,old,new,tolerance_m=0.05):
    old=coordinate(old)
    new=coordinate(new)
    if not math.isfinite(tolerance_m) or not 0<=tolerance_m<=2:
        raise StorageError("Shared vertex tolerance must be between 0 and 2 meters.")
    with _connect() as c:
        _required_project(c,project_id)
        _schema(c)
        total=c.execute("SELECT COUNT(*) FROM features WHERE project_id=?",(project_id,)).fetchone()[0]
        if total>500:
            raise StorageError("Shared editing is limited to 500 project features.")
        features=c.execute("SELECT * FROM features WHERE project_id=?",(project_id,)).fetchall()
        candidates=[]
        for row in features:
            geometry=json.loads(row["geometry"])
            if geometry.get("type") not in {"Polygon","MultiPolygon","LineString","MultiLineString"}:
                continue
            transformed,changed=_replace_vertices(geometry,old,new,tolerance_m)
            if not changed: continue
            layer=_feature_layer(c,project_id,row["id"])
            try:
                measure_geometry(transformed)
                valid=True;reason=None
            except GeometryError as error:
                valid=False;reason=str(error)
            candidates.append({
                "id":row["id"],"name":row["name"],"replaced_vertices":changed,
                "geometry":transformed,"revision":_revision(c,row["id"]),
                "valid":valid,"warning":reason,
                "locked":bool(layer["locked"]),"layer_id":layer["id"],
            })
    return {"affected":candidates,"count":len(candidates),
            "method":"Match existing vertices within geodesic tolerance; no automatic edge interpolation"}


def apply_shared_vertex(project_id,old,new,expected_revisions,tolerance_m=0.05):
    # A preview is advisory only. Repeat all validation inside a single
    # immediate transaction to avoid race conditions between collaborators.
    old=coordinate(old)
    new=coordinate(new)
    if not math.isfinite(tolerance_m) or not 0<=tolerance_m<=2:
        raise StorageError("Shared vertex tolerance must be 0–2 meters.")
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
        rows=c.execute("SELECT * FROM features WHERE project_id=?",(project_id,)).fetchall()
        if len(rows)>500: raise StorageError("Shared editing supports at most 500 features.")
        changes=[]
        for row in rows:
            original=json.loads(row["geometry"])
            if original.get("type") not in {"Polygon","MultiPolygon","LineString","MultiLineString"}:
                continue
            moved,count=_replace_vertices(original,old,new,tolerance_m)
            if not count: continue
            layer=_feature_layer(c,project_id,row["id"])
            if layer["locked"]: raise StorageError("Linked edit blocked by a locked layer.")
            revision=_revision(c,row["id"])
            if (row["id"] not in expected_revisions
                    or expected_revisions[row["id"]]!=revision):
                raise StorageError("Revision conflict in linked geometry edit.")
            try: measure_geometry(moved)
            except GeometryError as error: raise StorageError(str(error)) from error
            changes.append((row,moved,count,revision))
        if not changes: raise StorageError("No matching shared vertices found.")
        now=_now()
        for row,moved,count,revision in changes:
            if revision==0:
                c.execute(
                    "INSERT OR IGNORE INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
                    (row["id"],0,row["name"],row["geometry"],row["properties"],
                     row["source"],row["created_at"]),
                )
            serial=json.dumps(moved,allow_nan=False)
            c.execute("UPDATE features SET geometry=? WHERE id=? AND project_id=?",
                      (serial,row["id"],project_id))
            c.execute(
                "INSERT INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
                (row["id"],revision+1,row["name"],serial,row["properties"],
                 row["source"],now),
            )
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(now,project_id))
        return {"updated":[{"id":row["id"],"revision":revision+1,"moved_vertices":count}
                           for row,_,count,revision in changes],
                "count":len(changes),"atomic":True}
