"""SQLite R-tree bounds, viewport pages and safe spatial candidates.

Indexes track changes via SQLite triggers, including original and legacy
project writes. The numeric rowid key belongs only to the SQLite R-tree:
external feature identifiers remain stable UUIDs.
"""
import json
import sqlite3

from shapely.geometry import shape
from .database import StorageError,_connect,_required_project


def _bbox_json(data:str)->tuple:
    value=shape(json.loads(data))
    if value.is_empty:raise StorageError("Cannot index empty geographic geometry.")
    return value.bounds


def register_rtree_functions(conn:sqlite3.Connection)->None:
    """Register geometry UDFs on each fresh connection before any write."""
    if conn.in_transaction:
        # Replacing SQLite UDFs inside a running write transaction is invalid.
        raise StorageError("Spatial functions must be registered before writes.")
    for index,name in enumerate(("geo_minx","geo_miny","geo_maxx","geo_maxy")):
        conn.create_function(name,1,lambda data,i=index:_bbox_json(data)[i],
                             deterministic=True)


def prepare_rtree(conn:sqlite3.Connection)->None:
    """Create/update spatial triggers and rebuild missing index rows.

    This is deliberately an explicit maintenance operation; the fast
    connection path initializes it once using the SQLite user_version marker.
    """
    if not conn.in_transaction:
        register_rtree_functions(conn)
    conn.executescript("""
    CREATE VIRTUAL TABLE IF NOT EXISTS feature_bounds USING rtree(
      feature_rowid,minx,maxx,miny,maxy
    );
    CREATE TRIGGER IF NOT EXISTS feature_bounds_insert AFTER INSERT ON features
    BEGIN
      INSERT OR REPLACE INTO feature_bounds VALUES(
        new.rowid,geo_minx(new.geometry),geo_maxx(new.geometry),
        geo_miny(new.geometry),geo_maxy(new.geometry)
      );
    END;
    CREATE TRIGGER IF NOT EXISTS feature_bounds_update AFTER UPDATE OF geometry ON features
    BEGIN
      INSERT OR REPLACE INTO feature_bounds VALUES(
        new.rowid,geo_minx(new.geometry),geo_maxx(new.geometry),
        geo_miny(new.geometry),geo_maxy(new.geometry)
      );
    END;
    CREATE TRIGGER IF NOT EXISTS feature_bounds_delete AFTER DELETE ON features
    BEGIN DELETE FROM feature_bounds WHERE feature_rowid=old.rowid; END;
    """)
    # Backfill old databases without scanning/reparsing their features on
    # every API query (index count is checked once per connection).
    count=conn.execute("SELECT count(*) FROM features").fetchone()[0]
    indexed=conn.execute("SELECT count(*) FROM feature_bounds").fetchone()[0]
    if indexed!=count:
        conn.execute("""INSERT OR REPLACE INTO feature_bounds
            SELECT rowid,geo_minx(geometry),geo_maxx(geometry),
                geo_miny(geometry),geo_maxy(geometry)
            FROM features WHERE rowid NOT IN (
                SELECT feature_rowid FROM feature_bounds
            )""")
        conn.execute("""DELETE FROM feature_bounds WHERE feature_rowid NOT IN
                        (SELECT rowid FROM features)""")


def _bounds(bbox):
    if len(bbox)!=4:
        raise StorageError("BBox must contain four WGS84 coordinates.")
    west,south,east,north=[float(x) for x in bbox]
    import math
    if not all(map(math.isfinite,(west,south,east,north))) or not (
        -180<=west<east<=180 and -90<=south<north<=90
    ):
        raise StorageError("Invalid WGS84 bbox; crossing the dateline is unsupported.")
    return west,south,east,north


def bounding_candidates(project_id,bbox,layer_ids=None,visible_only=False,
                        max_candidates=25000):
    west,south,east,north=_bounds(bbox)
    from .workspace import _schema,_default
    with _connect() as conn:
        _required_project(conn,project_id)
        _schema(conn)
        _default(conn,project_id)
        if layer_ids:
            # Authorization: each layer id must belong to this project.
            allowed={row["id"] for row in conn.execute(
                "SELECT id FROM geo_layers WHERE project_id=?",(project_id,))}
            if any(lid not in allowed for lid in layer_ids):
                raise StorageError("Layer not found.")
        sql="""SELECT f.*,COALESCE(m.layer_id,default_layer.id) AS layer_id,
            COALESCE((SELECT MAX(revision) FROM geo_feature_revisions r
                WHERE r.feature_id=f.id),0) AS revision
            FROM features f
            JOIN feature_bounds b ON b.feature_rowid=f.rowid
            LEFT JOIN geo_layer_members m ON m.feature_id=f.id
            JOIN geo_layers default_layer ON default_layer.id=(
                SELECT id FROM geo_layers WHERE project_id=f.project_id
                ORDER BY created_at,id LIMIT 1
            )
            LEFT JOIN geo_layers assigned ON assigned.id=m.layer_id
            WHERE f.project_id=? AND b.maxx>=? AND b.minx<=?
             AND b.maxy>=? AND b.miny<=?"""
        params=[project_id,west,east,south,north]
        if visible_only:
            sql+=" AND COALESCE(assigned.visible,default_layer.visible)=1"
        if layer_ids:
            sql+=" AND COALESCE(m.layer_id,default_layer.id) IN ("+",".join("?" for _ in layer_ids)+")"
            params+=layer_ids
        sql+=" ORDER BY f.created_at,f.id LIMIT ?"
        rows=conn.execute(sql,(*params,max_candidates+1)).fetchall()
        if len(rows)>max_candidates:
            raise StorageError("Too many spatial candidates; narrow the view or layer filter.")
    results=[]
    for row in rows:
        item=dict(row);item["geometry"]=json.loads(item["geometry"])
        item["properties"]=json.loads(item["properties"])
        results.append(item)
    return results


def page_features(project_id,bbox,limit=250,offset=0,layer_ids=None,
                  visible_only=True):
    """True indexed SQL COUNT + LIMIT/OFFSET, no 25K candidate materialization.

    Exact geometric relations belong to selection API. A viewport query
    returns R-tree bounding-box matches for vector tiles or workspace
    pagination without constructing thousands of Shapely geometries.
    """
    if not 1<=limit<=1000 or not 0<=offset<=1_000_000:
        raise StorageError("Spatial page must have limit 1–1000 and offset at most 1 million.")
    west,south,east,north=_bounds(bbox)
    from .workspace import _schema,_default
    from geometry.measure import measure_geometry
    with _connect() as conn:
        _required_project(conn,project_id)
        _schema(conn);_default(conn,project_id)
        if layer_ids:
            actual={r["id"] for r in conn.execute(
                "SELECT id FROM geo_layers WHERE project_id=?",(project_id,))}
            if any(lid not in actual for lid in layer_ids):
                raise StorageError("Layer not found.")
        from_clause=""" FROM features f
            JOIN feature_bounds b ON b.feature_rowid=f.rowid
            LEFT JOIN geo_layer_members m ON m.feature_id=f.id
            JOIN geo_layers default_layer ON default_layer.id=(
                SELECT id FROM geo_layers WHERE project_id=f.project_id
                ORDER BY created_at,id LIMIT 1
            )
            LEFT JOIN geo_layers assigned ON assigned.id=m.layer_id
            WHERE f.project_id=? AND b.maxx>=? AND b.minx<=?
            AND b.maxy>=? AND b.miny<=?"""
        params=[project_id,west,east,south,north]
        if visible_only:
            from_clause+=" AND COALESCE(assigned.visible,default_layer.visible)=1"
        if layer_ids:
            from_clause+=" AND COALESCE(m.layer_id,default_layer.id) IN ("+(
                ",".join("?" for _ in layer_ids))+")"
            params.extend(layer_ids)
        total=conn.execute("SELECT count(*)"+from_clause,params).fetchone()[0]
        rows=conn.execute(
            """SELECT f.*,COALESCE(m.layer_id,default_layer.id) AS layer_id,
              COALESCE((SELECT MAX(r.revision) FROM geo_feature_revisions r
                WHERE r.feature_id=f.id),0) AS revision"""+
            from_clause+" ORDER BY f.created_at,f.id LIMIT ? OFFSET ?",
            [*params,limit,offset]).fetchall()
    page=[]
    for row in rows:
        item=dict(row)
        item["geometry"]=json.loads(item["geometry"])
        item["properties"]=json.loads(item["properties"])
        item["measurement"]=measure_geometry(item["geometry"])
        page.append(item)
    return {"results":page,"total":total,
            "limit":limit,"offset":offset,"indexed":True}
