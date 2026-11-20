"""Project attribute table with bounded queries and atomic, versioned edits."""

import json
from typing import Any

from geometry.measure import GeometryError, measure_geometry
from .database import StorageError, _connect, _now, _required_project
from .workspace import _schema, _feature, _feature_layer, _revision


def _safe_field(field):
    if not isinstance(field,str) or not 1<=len(field)<=64 or field.startswith("_"):
        raise StorageError("Property name must be 1–64 characters, without reserved prefix.")


def query_attributes(project_id,field=None,operator="contains",value=None,limit=100,offset=0):
    if not 1<=limit<=200 or not 0<=offset<=10000:
        raise StorageError("Invalid attribute pagination.")
    if field is not None:
        _safe_field(field)
    if operator not in {"contains","equals","gte","lte","exists"}:
        raise StorageError("Unsupported attribute predicate.")
    with _connect() as c:
        _required_project(c,project_id)
        all_rows=c.execute(
            "SELECT id,name,properties,source FROM features WHERE project_id=? ORDER BY created_at,id LIMIT 10001",
            (project_id,),
        ).fetchall()
        if len(all_rows)>10000:
            raise StorageError("Attribute scans above 10,000 features need an indexed database.")
    rows=[]
    for row in all_rows:
        props=json.loads(row["properties"])
        actual=(row["name"] if field=="name" else row["source"] if field=="source" else props.get(field)) if field else None
        selected=True
        if field:
            if operator=="exists": selected=actual is not None
            elif operator=="contains":selected=value is not None and str(value).casefold() in str(actual or "").casefold()
            elif operator=="equals":selected=actual==value
            else:
                try:
                    if isinstance(actual,bool) or actual is None: selected=False
                    else:
                        numeric=float(actual); target=float(value)
                        selected=numeric>=target if operator=="gte" else numeric<=target
                except (TypeError,ValueError):selected=False
        if selected: rows.append({"id":row["id"],"name":row["name"],"source":row["source"],"properties":props})
    return {"results":rows[offset:offset+limit],"total":len(rows),
            "fields":sorted({key for row in rows for key in row["properties"]})[:200]}


def update_properties(project_id,updates:list[dict[str,Any]]):
    if not 1<=len(updates)<=100:
        raise StorageError("Update between 1 and 100 features.")
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
        checked=[]
        unique=set()
        for item in updates:
            feature_id=item.get("id")
            if feature_id in unique: raise StorageError("Duplicate feature in batch.")
            unique.add(feature_id)
            original=_feature(c,project_id,feature_id)
            if _feature_layer(c,project_id,feature_id)["locked"]:
                raise StorageError("Feature layer is locked.")
            revision=_revision(c,feature_id)
            if item.get("expected_revision")!=revision:
                raise StorageError("Revision conflict in attribute update.")
            values=item.get("properties")
            if not isinstance(values,dict) or len(values)>100:
                raise StorageError("Provide an object containing up to 100 attribute changes.")
            for key in values:_safe_field(key)
            props=json.loads(original["properties"])
            props.update(values)
            if len(json.dumps(props,allow_nan=False))>100000:
                raise StorageError("Attribute data exceeds storage limits.")
            checked.append((original,revision,props))
        now=_now()
        for original,rev,props in checked:
            uid=original["id"]
            if rev==0:
                c.execute("INSERT OR IGNORE INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
                          (uid,0,original["name"],original["geometry"],original["properties"],
                           original["source"],original["created_at"]))
            text=json.dumps(props,allow_nan=False)
            c.execute("UPDATE features SET properties=? WHERE id=?",(text,uid))
            c.execute("INSERT INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
                      (uid,rev+1,original["name"],original["geometry"],text,original["source"],now))
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(now,project_id))
    return {"updated":[{"id":original["id"],"revision":rev+1} for original,rev,_ in checked],
            "count":len(checked),"atomic":True}
