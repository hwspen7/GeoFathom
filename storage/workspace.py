"""Persistent, project-scoped GIS layers and immutable geometry revision history.

Layers are views over existing project features. Every geometry edit is a
transaction recording before and after snapshots, with optimistic revision
checks. Hidden layers affect display, locked layers forbid mutations.
"""

import json
import re
from uuid import uuid4

from geometry.measure import GeometryError, measure_geometry
from .database import StorageError, _connect, _now, _required_project, add_features, list_features

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DEFAULT = "Measurements"


def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS geo_layers (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      color TEXT NOT NULL,
      visible INTEGER NOT NULL DEFAULT 1,
      locked INTEGER NOT NULL DEFAULT 0,
      z_index INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS geo_layers_project_idx ON geo_layers(project_id);
    CREATE TABLE IF NOT EXISTS geo_layer_members (
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      feature_id TEXT PRIMARY KEY REFERENCES features(id) ON DELETE CASCADE,
      layer_id TEXT NOT NULL REFERENCES geo_layers(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS geo_feature_revisions (
      feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,
      revision INTEGER NOT NULL,
      name TEXT NOT NULL,
      geometry TEXT NOT NULL,
      properties TEXT NOT NULL,
      source TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY(feature_id, revision)
    );
    """)


def _default(conn, project_id):
    row = conn.execute(
        "SELECT * FROM geo_layers WHERE project_id=? ORDER BY z_index,id LIMIT 1",
        (project_id,),
    ).fetchone()
    if row:
        return row["id"]
    uid = str(uuid4())
    conn.execute(
        "INSERT INTO geo_layers VALUES (?,?,?,?,?,?,?,?)",
        (uid, project_id, _DEFAULT, "#2563eb", 1, 0, 0, _now()),
    )
    return uid


def _layer(conn, project_id, layer_id):
    row = conn.execute(
        "SELECT * FROM geo_layers WHERE project_id=? AND id=?",
        (project_id, layer_id),
    ).fetchone()
    if row is None:
        raise StorageError("Layer not found.")
    return dict(row)


def layers(project_id):
    with _connect() as c:
        _required_project(c, project_id)
        _schema(c)
        _default(c, project_id)
        return [dict(row) for row in c.execute(
            "SELECT * FROM geo_layers WHERE project_id=? ORDER BY z_index,id", (project_id,),
        )]


def add_layer(project_id, name, color="#2563eb"):
    if not name.strip() or len(name)>100 or not _HEX.fullmatch(color):
        raise StorageError("Layer name or hex color is invalid.")
    with _connect() as c:
        _required_project(c,project_id)
        _schema(c)
        _default(c,project_id)
        if c.execute("SELECT COUNT(*) FROM geo_layers WHERE project_id=?", (project_id,)).fetchone()[0]>=100:
            raise StorageError("A project supports at most 100 layers.")
        idx=c.execute("SELECT COALESCE(MAX(z_index),0)+1 FROM geo_layers WHERE project_id=?", (project_id,)).fetchone()[0]
        uid=str(uuid4())
        c.execute("INSERT INTO geo_layers VALUES (?,?,?,?,?,?,?,?)",
                  (uid,project_id,name.strip(),color,1,0,idx,_now()))
        return _layer(c,project_id,uid)


def edit_layer(project_id, layer_id, changes):
    permitted={"name","color","visible","locked","z_index"}
    if not changes or any(k not in permitted for k in changes):
        raise StorageError("Unsupported layer edit.")
    if "name" in changes and (not str(changes["name"]).strip() or len(changes["name"])>100):
        raise StorageError("Layer name is required.")
    if "color" in changes and not _HEX.fullmatch(str(changes["color"])):
        raise StorageError("Use a #RRGGBB layer color.")
    if "z_index" in changes and not (-1000<=changes["z_index"]<=1000):
        raise StorageError("Layer ordering must be between -1000 and 1000.")
    with _connect() as c:
        _required_project(c, project_id)
        _schema(c)
        _layer(c,project_id,layer_id)
        payload={k:(int(v) if k in {"visible","locked"} else v) for k,v in changes.items()}
        sql=", ".join(f"{key}=?" for key in payload)
        c.execute(f"UPDATE geo_layers SET {sql} WHERE project_id=? AND id=?",
                  (*payload.values(),project_id,layer_id))
        return _layer(c,project_id,layer_id)


def remove_layer(project_id, layer_id):
    with _connect() as c:
        _required_project(c,project_id)
        _schema(c)
        layer=_layer(c,project_id,layer_id)
        if c.execute("SELECT COUNT(*) FROM geo_layers WHERE project_id=?", (project_id,)).fetchone()[0]==1:
            raise StorageError("A project must retain at least one layer.")
        if c.execute("SELECT COUNT(*) FROM geo_layer_members WHERE layer_id=?", (layer_id,)).fetchone()[0]:
            raise StorageError("Move or delete this layer's features before removing it.")
        c.execute("DELETE FROM geo_layers WHERE id=? AND project_id=?",(layer_id,project_id))


def _feature(c,project_id,feature_id):
    row=c.execute("SELECT * FROM features WHERE project_id=? AND id=?", (project_id,feature_id)).fetchone()
    if row is None: raise StorageError("Feature not found.")
    return dict(row)


def _feature_layer(c,project_id,feature_id):
    row=c.execute(
        "SELECT l.* FROM geo_layers l JOIN geo_layer_members m ON l.id=m.layer_id "
        "WHERE m.project_id=? AND m.feature_id=?", (project_id,feature_id),
    ).fetchone()
    return dict(row) if row else _layer(c,project_id,_default(c,project_id))


def _revision(c,feature_id):
    return c.execute(
        "SELECT COALESCE(MAX(revision),0) FROM geo_feature_revisions WHERE feature_id=?",
        (feature_id,),
    ).fetchone()[0]


def workspace(project_id):
    # The default layer is lazily created so existing databases remain readable.
    items=list_features(project_id,limit=200)
    all_layers=layers(project_id)
    with _connect() as c:
        _schema(c)
        assignments={row["feature_id"]:row["layer_id"] for row in c.execute(
            "SELECT feature_id,layer_id FROM geo_layer_members WHERE project_id=?", (project_id,),
        )}
        revisions={row["feature_id"]:row["revision"] for row in c.execute(
            "SELECT feature_id,MAX(revision) AS revision FROM geo_feature_revisions "
            "GROUP BY feature_id",
        )}
    for item in items["results"]:
        item["layer_id"]=assignments.get(item["id"],all_layers[0]["id"])
        item["revision"]=revisions.get(item["id"],0)
    return {"layers":all_layers,"features":items["results"],"total":items["total"]}


def update_feature(project_id,feature_id,geometry=None,name=None,properties=None,
                   layer_id=None,expected_revision=None):
    with _connect() as c:
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
        _schema(c)
        original=_feature(c,project_id,feature_id)
        existing_layer=_feature_layer(c,project_id,feature_id)
        target_layer=_layer(c,project_id,layer_id) if layer_id else existing_layer
        if existing_layer["locked"] or target_layer["locked"]:
            raise StorageError("The selected feature layer is locked.")
        current=_revision(c,feature_id)
        if expected_revision is not None and expected_revision != current:
            raise StorageError("Revision conflict. Reload the latest feature.")
        geom=geometry if geometry is not None else json.loads(original["geometry"])
        props=properties if properties is not None else json.loads(original["properties"])
        if not isinstance(props,dict):
            raise StorageError("Feature properties must be a JSON object.")
        if len(json.dumps(props,allow_nan=False))>100000:
            raise StorageError("Feature properties are too large.")
        try:
            measurement=measure_geometry(geom)
        except GeometryError as error:
            raise StorageError(str(error)) from error
        new_name=(name if name is not None else original["name"]).strip()
        if not new_name or len(new_name)>200: raise StorageError("Feature name is invalid.")
        if current==0:
            # Revision zero is the original baseline, even for legacy records.
            c.execute(
                "INSERT OR IGNORE INTO geo_feature_revisions VALUES (?,?,?,?,?,?,?)",
                (feature_id,0,original["name"],original["geometry"],
                 original["properties"],original["source"],original["created_at"]),
            )
        revision=current+1
        serialized=json.dumps(geom,allow_nan=False)
        details=json.dumps(props,allow_nan=False)
        c.execute("UPDATE features SET geometry=?, name=?, properties=? WHERE project_id=? AND id=?",
                  (serialized,new_name,details,project_id,feature_id))
        c.execute("INSERT INTO geo_feature_revisions VALUES (?,?,?,?,?,?,?)",
                  (feature_id,revision,new_name,serialized,details,original["source"],_now()))
        c.execute(
            "INSERT INTO geo_layer_members(project_id,feature_id,layer_id) VALUES(?,?,?) "
            "ON CONFLICT(feature_id) DO UPDATE SET layer_id=excluded.layer_id",
            (project_id,feature_id,target_layer["id"]),
        )
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(_now(),project_id))
        return {"id":feature_id,"project_id":project_id,"name":new_name,
                "geometry":geom,"properties":props,"measurement":measurement,
                "source":original["source"],"layer_id":target_layer["id"],
                "revision":revision}


def feature_history(project_id,feature_id):
    with _connect() as c:
        _required_project(c,project_id)
        _schema(c)
        original=_feature(c,project_id,feature_id)
        rows=c.execute(
            "SELECT * FROM geo_feature_revisions WHERE feature_id=? ORDER BY revision DESC LIMIT 100",
            (feature_id,),
        ).fetchall()
    if not rows:
        return {"feature_id":feature_id,"current_revision":0,
                "versions":[{"revision":0,"name":original["name"],
                            "geometry":json.loads(original["geometry"]),
                            "properties":json.loads(original["properties"]),
                            "created_at":original["created_at"]}]}
    return {"feature_id":feature_id,"current_revision":rows[0]["revision"],
            "versions":[{"revision":row["revision"],"name":row["name"],
                         "geometry":json.loads(row["geometry"]),
                         "properties":json.loads(row["properties"]),
                         "created_at":row["created_at"]} for row in rows]}


def restore_version(project_id,feature_id,revision):
    # Delegate to the ordinary update pathway: a restore is a new revision.
    history=feature_history(project_id,feature_id)
    selected=next((row for row in history["versions"] if row["revision"]==revision),None)
    if selected is None: raise StorageError("Revision not found.")
    return update_feature(
        project_id,feature_id,geometry=selected["geometry"],
        name=selected["name"],properties=selected["properties"],
        expected_revision=history["current_revision"],
    )


def copy_feature(project_id,feature_id):
    with _connect() as c:
        _required_project(c,project_id)
        _schema(c)
        original=_feature(c,project_id,feature_id)
        layer=_feature_layer(c,project_id,feature_id)
        if layer["locked"]: raise StorageError("The selected feature layer is locked.")
    result=add_features(project_id,[{
        "name":original["name"]+" copy",
        "geometry":json.loads(original["geometry"]),
        "properties":{**json.loads(original["properties"]),"copied_from":feature_id},
        "source":original["source"],
    }])["results"][0]
    update_feature(project_id,result["id"],layer_id=layer["id"])
    return result
