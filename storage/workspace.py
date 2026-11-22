"""Persistent, project-scoped GIS layers and immutable geometry revision history.

Layers are views over existing project features. Every geometry edit is a
transaction recording before and after snapshots, with optimistic revision
checks. Hidden layers affect display, locked layers forbid mutations.
"""

import json
import re
from uuid import uuid4

from geometry.measure import GeometryError, measure_geometry
from .database import StorageError, _connect, _now, _required_project, _record_feature

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
    CREATE TABLE IF NOT EXISTS geo_feature_trash (
      feature_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      layer_id TEXT NOT NULL,
      name TEXT NOT NULL,
      deleted_at TEXT NOT NULL,
      payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS geo_feature_trash_project ON geo_feature_trash(project_id,deleted_at);
    """)


def _default(conn, project_id):
    row = conn.execute(
        "SELECT * FROM geo_layers WHERE project_id=? ORDER BY created_at,id LIMIT 1",
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
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c, project_id)
        _default(c, project_id)
        from .cartography import read_style_in_connection
        return [
            {**dict(row),**read_style_in_connection(c,row["id"])}
            for row in c.execute(
                "SELECT * FROM geo_layers WHERE project_id=? ORDER BY z_index,id",
                (project_id,),
            ).fetchall()
        ]


def add_layer(project_id, name, color="#2563eb"):
    if not name.strip() or len(name)>100 or not _HEX.fullmatch(color):
        raise StorageError("Layer name or hex color is invalid.")
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
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
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
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
    # Use one coherent transaction for geometry, layer definitions, styling,
    # counts, and optimistic revision numbers. A concurrent writer cannot
    # pair an old geometry with a newer revision. Initialize legacy default
    # layers in the same transaction, then measure outside the write lock.
    from .cartography import read_style_in_connection
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c, project_id)
        default_id=_default(c,project_id)
        all_layers=[
            {**dict(row),**read_style_in_connection(c,row["id"])}
            for row in c.execute(
                "SELECT * FROM geo_layers WHERE project_id=? ORDER BY z_index,id",
                (project_id,)).fetchall()
        ]
        total=c.execute("SELECT count(*) FROM features WHERE project_id=?",(project_id,)).fetchone()[0]
        rows=c.execute("""
            SELECT f.*,COALESCE(m.layer_id,?) AS layer_id,
                COALESCE((SELECT MAX(r.revision) FROM geo_feature_revisions r
                         WHERE r.feature_id=f.id),0) AS revision
            FROM features f LEFT JOIN geo_layer_members m
                ON m.feature_id=f.id AND m.project_id=f.project_id
            WHERE f.project_id=? ORDER BY f.created_at,f.id LIMIT 200
        """,(default_id,project_id)).fetchall()
    results=[]
    for row in rows:
        item=dict(row)
        item["geometry"]=json.loads(item["geometry"])
        item["properties"]=json.loads(item["properties"])
        item["measurement"]=measure_geometry(item["geometry"])
        results.append(item)
    return {"layers":all_layers,"features":results,"total":total}


def update_feature(project_id,feature_id,geometry=None,name=None,properties=None,
                   layer_id=None,expected_revision=None):
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
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
                "created_at":original["created_at"],"revision":revision}


def feature_history(project_id,feature_id):
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN")
        _required_project(c,project_id)
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
                            "created_at":original["created_at"],
                            "measurement":measure_geometry(json.loads(original["geometry"]))}]}
    return {"feature_id":feature_id,"current_revision":rows[0]["revision"],
            "versions":[{"revision":row["revision"],"name":row["name"],
                         "geometry":json.loads(row["geometry"]),
                         "properties":json.loads(row["properties"]),
                         "created_at":row["created_at"],
                         "measurement":measure_geometry(json.loads(row["geometry"]))}
                        for row in rows]}


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


def add_in_layer(project_id, inputs, layer_id=None):
    """Create and assign features atomically, respecting lock state."""
    if not 1 <= len(inputs) <= 512:
        raise StorageError("Submit between 1 and 512 geographic features.")
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
        target=_layer(c,project_id,layer_id or _default(c,project_id))
        if target["locked"]: raise StorageError("The target layer is locked.")
        results=[]
        vertices=0
        for item in inputs:
            props=item.get("properties",{})
            if not isinstance(props,dict) or len(json.dumps(props,allow_nan=False))>100000:
                raise StorageError("Feature properties must be a bounded JSON object.")
            try:
                new=_record_feature(
                    c,project_id,item.get("geometry"),
                    str(item.get("name") or "Untitled feature").strip()[:200],
                    str(item.get("source") or "User supplied").strip()[:200],
                    props,
                )
            except (GeometryError,TypeError,ValueError) as error:
                raise StorageError(str(error)) from error
            vertices+=new["measurement"]["coordinate_count"]
            if vertices>400000:
                raise StorageError("Atomic batch exceeds 400,000 geometry vertices.")
            c.execute(
                "INSERT INTO geo_layer_members(project_id,feature_id,layer_id) VALUES(?,?,?)",
                (project_id,new["id"],target["id"]),
            )
            new["layer_id"]=target["id"]
            new["revision"]=0
            results.append(new)
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(_now(),project_id))
        return {"results":results,"created":len(results)}


def can_delete_feature(project_id,feature_id):
    with _connect() as c:
        _required_project(c,project_id)
        _schema(c)
        _feature(c,project_id,feature_id)
        if _feature_layer(c,project_id,feature_id)["locked"]:
            raise StorageError("The feature layer is locked.")


def copy_feature(project_id,feature_id):
    # The source lock check, snapshot and copy write belong to one
    # transaction; a concurrent layer change cannot intervene.
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
        original=_feature(c,project_id,feature_id)
        layer=_feature_layer(c,project_id,feature_id)
        if layer["locked"]: raise StorageError("The selected feature layer is locked.")
        props={**json.loads(original["properties"]),"copied_from":feature_id}
        if len(json.dumps(props,allow_nan=False))>100000:
            raise StorageError("Feature properties are too large.")
        try:
            new=_record_feature(c,project_id,json.loads(original["geometry"]),
                (original["name"][:195]+" copy").strip(),original["source"],props)
        except (GeometryError,TypeError,ValueError) as error:
            raise StorageError(str(error)) from error
        c.execute("INSERT INTO geo_layer_members(project_id,feature_id,layer_id) VALUES(?,?,?)",
                  (project_id,new["id"],layer["id"]))
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(_now(),project_id))
        return {**new,"layer_id":layer["id"],"revision":0}


def delete_feature_guarded(project_id, feature_id, expected_revision=None):
    """Move a feature, its exact identity and all revisions to project trash atomically."""
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c, project_id)
        original=_feature(c,project_id,feature_id)
        layer=_feature_layer(c,project_id,feature_id)
        if layer["locked"]:
            raise StorageError("The feature layer is locked.")
        current=_revision(c,feature_id)
        if expected_revision is not None and expected_revision!=current:
            raise StorageError("Revision conflict. Reload the latest feature.")
        history=[dict(row) for row in c.execute(
            "SELECT * FROM geo_feature_revisions WHERE feature_id=? ORDER BY revision",(feature_id,))]
        payload=json.dumps({"feature":original,"history":history},allow_nan=False)
        if len(payload)>64_000_000:
            raise StorageError("Feature history exceeds the recoverable trash record budget.")
        c.execute("INSERT INTO geo_feature_trash VALUES(?,?,?,?,?,?)",
            (feature_id,project_id,layer["id"],original["name"],_now(),payload))
        c.execute("DELETE FROM features WHERE id=? AND project_id=?", (feature_id, project_id))
        c.execute("UPDATE projects SET updated_at=? WHERE id=?", (_now(), project_id))


def trash_features(project_id,limit=100,offset=0):
    with _connect() as c:
        _schema(c)
        _required_project(c,project_id)
        rows=c.execute("""SELECT feature_id,layer_id,name,deleted_at FROM geo_feature_trash
            WHERE project_id=? ORDER BY deleted_at DESC,feature_id LIMIT ? OFFSET ?""",
            (project_id,limit,offset)).fetchall()
        total=c.execute("SELECT count(*) FROM geo_feature_trash WHERE project_id=?",(project_id,)).fetchone()[0]
        return {"items":[dict(row) for row in rows],"total":total}


def restore_deleted_feature(project_id,feature_id):
    """Restore the same feature ID and revisions, recording a new restore revision."""
    with _connect() as c:
        _schema(c)
        c.execute("BEGIN IMMEDIATE")
        _required_project(c,project_id)
        row=c.execute("SELECT * FROM geo_feature_trash WHERE project_id=? AND feature_id=?",
            (project_id,feature_id)).fetchone()
        if row is None:raise StorageError("Deleted feature not found.")
        layer=_layer(c,project_id,row["layer_id"])
        if layer["locked"]:raise StorageError("The original feature layer is locked.")
        if c.execute("SELECT 1 FROM features WHERE id=?",(feature_id,)).fetchone():
            raise StorageError("Feature identity conflict.")
        data=json.loads(row["payload"])
        f=data["feature"]
        geometry=json.loads(f["geometry"]);properties=json.loads(f["properties"])
        measured=measure_geometry(geometry)
        c.execute("""INSERT INTO features(id,project_id,name,geometry,properties,source,created_at)
            VALUES(?,?,?,?,?,?,?)""",(feature_id,project_id,f["name"],f["geometry"],f["properties"],f["source"],f["created_at"]))
        c.execute("INSERT INTO geo_layer_members VALUES(?,?,?)",(project_id,feature_id,layer["id"]))
        history=data["history"]
        for rev in history:
            c.execute("INSERT INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
                (feature_id,rev["revision"],rev["name"],rev["geometry"],rev["properties"],rev["source"],rev["created_at"]))
        if not history:
            c.execute("INSERT INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
                (feature_id,0,f["name"],f["geometry"],f["properties"],f["source"],f["created_at"]))
        revision=max((rev["revision"] for rev in history),default=0)+1
        stamp=_now()
        c.execute("INSERT INTO geo_feature_revisions VALUES(?,?,?,?,?,?,?)",
            (feature_id,revision,f["name"],f["geometry"],f["properties"],f["source"],stamp))
        c.execute("DELETE FROM geo_feature_trash WHERE feature_id=? AND project_id=?",(feature_id,project_id))
        c.execute("UPDATE projects SET updated_at=? WHERE id=?",(stamp,project_id))
        return {**f,"geometry":geometry,"properties":properties,"measurement":measured,
            "layer_id":layer["id"],"revision":revision}
