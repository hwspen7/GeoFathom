"""Optional transactional PostGIS mirror with GiST spatial indexing.

The SQLite workspace remains the authoritative local editing store. PostGIS
is a configurable query-serving mirror; synchronization replaces a project
snapshot atomically so a failed import never exposes partial data. Credentials
come only from server environment, never browser requests or returned JSON.
"""
import json
import os

from storage.database import StorageError,_connect,_required_project
from storage.workspace import _schema,_default


class PostGISError(ValueError):pass


def _connect_pg():
    dsn=os.getenv("GEOFATHOM_POSTGIS_DSN","").strip()
    if not dsn:raise PostGISError("Configure GEOFATHOM_POSTGIS_DSN before using PostGIS.")
    try:
        import psycopg
    except ImportError as error:
        raise PostGISError('Install optional dependencies: pip install -e ".[postgis]".') from error
    return psycopg.connect(dsn,connect_timeout=5)


def _prepare(conn):
    conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    conn.execute("""CREATE TABLE IF NOT EXISTS geofathom_features(
      project_id TEXT NOT NULL,
      id TEXT NOT NULL,
      layer_id TEXT,
      revision INTEGER NOT NULL DEFAULT 0,
      name TEXT NOT NULL,
      source TEXT NOT NULL,
      properties JSONB NOT NULL,
      geom geometry(Geometry,4326) NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY(project_id,id)
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS geofathom_features_geom_gix
        ON geofathom_features USING GIST(geom)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS geofathom_features_project_idx
        ON geofathom_features(project_id)""")


def status():
    if not os.getenv("GEOFATHOM_POSTGIS_DSN","").strip():
        return {"configured":False,"connected":False,"engine":"postgis",
                "note":"Set GEOFATHOM_POSTGIS_DSN to enable an optional spatial query mirror."}
    try:
        with _connect_pg() as conn:
            installed=conn.execute("SELECT postgis_version()").fetchone()[0]
            return {"configured":True,"connected":True,"engine":"postgis",
                    "postgis_version":installed,"spatial_index":"GiST",
                    "note":"SQLite remains authoritative; sync is explicit."}
    except Exception:
        return {"configured":True,"connected":False,"engine":"postgis",
                "note":"PostGIS connection is not ready; verify credentials, server and extension."}


def sync_project(project_id:str,max_features:int=100000)->dict:
    if not 1<=max_features<=100000:
        raise PostGISError("Max features must be 1–100,000.")
    with _connect() as local:
        _required_project(local,project_id)
        _schema(local);default=_default(local,project_id)
        count=local.execute("SELECT count(*) FROM features WHERE project_id=?",(project_id,)).fetchone()[0]
        if count>max_features:
            raise PostGISError("Project exceeds the configured PostGIS sync cap.")
        try:
            with _connect_pg() as remote:
                _prepare(remote)
                # PostgreSQL serializes concurrent syncs for this project.
                remote.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(project_id,))
                remote.execute("DELETE FROM geofathom_features WHERE project_id=%s",(project_id,))
                offset=0
                while offset<count:
                    rows=local.execute("""SELECT f.*,COALESCE(m.layer_id,?) AS layer_id,
                         COALESCE((SELECT MAX(r.revision) FROM geo_feature_revisions r
                           WHERE r.feature_id=f.id),0) AS revision
                         FROM features f LEFT JOIN geo_layer_members m ON m.feature_id=f.id
                         WHERE f.project_id=? ORDER BY f.created_at,f.id LIMIT 500 OFFSET ?""",
                        (default,project_id,offset)).fetchall()
                    if not rows:break
                    batch=[(project_id,r["id"],r["layer_id"],r["revision"],r["name"],
                            r["source"],json.dumps(json.loads(r["properties"])),
                            json.dumps(json.loads(r["geometry"]))) for r in rows]
                    remote.executemany("""INSERT INTO geofathom_features(
                      project_id,id,layer_id,revision,name,source,properties,geom)
                      VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,
                             ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))""",batch)
                    offset+=len(rows)
                return {"project_id":project_id,"synchronized":offset,
                        "source":"SQLite","target":"PostGIS","atomic":True,
                        "index":"GiST geometry(Geometry,4326)",
                        "note":"Snapshot mirrored; re-sync after subsequent local edits."}
        except Exception as error:
            raise PostGISError("PostGIS transaction failed; check service logs and configuration.") from error


def spatial_page(project_id,bbox,limit=250,offset=0,relation="intersects")->dict:
    from storage.paging import _bounds
    from storage.database import get_project
    get_project(project_id)
    west,south,east,north=_bounds(bbox)
    if not 1<=limit<=1000 or not 0<=offset<=1_000_000:
        raise PostGISError("PostGIS page must have limit 1–1000 and offset <= 1 million.")
    try:
        with _connect_pg() as conn:
            _prepare(conn)
            params=(project_id,west,south,east,north)
            condition="""project_id=%s AND geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)
              AND ST_Intersects(geom,ST_MakeEnvelope(%s,%s,%s,%s,4326))"""
            doubled=(*params,west,south,east,north)
            total=conn.execute("SELECT COUNT(*) FROM geofathom_features WHERE "+condition,
                               doubled).fetchone()[0]
            rows=conn.execute("""SELECT id,project_id,layer_id,revision,name,source,
                    properties,ST_AsGeoJSON(geom) AS geometry
                    FROM geofathom_features WHERE """+condition+
                    " ORDER BY id LIMIT %s OFFSET %s",(*doubled,limit,offset)).fetchall()
            data=[{"id":r[0],"project_id":r[1],"layer_id":r[2],
                   "revision":r[3],"name":r[4],"source":r[5],
                   "properties":r[6],"geometry":json.loads(r[7])} for r in rows]
            return {"results":data,"total":total,"limit":limit,"offset":offset,
                    "indexed":True,"source":"PostGIS GiST spatial query"}
    except Exception as error:
        raise PostGISError("PostGIS query failed; verify service and schema.") from error


def purge_project(project_id):
    try:
        with _connect_pg() as conn:
            _prepare(conn)
            result=conn.execute("DELETE FROM geofathom_features WHERE project_id=%s",
                                (project_id,))
            return {"project_id":project_id,"removed":result.rowcount}
    except Exception as error:
        raise PostGISError("PostGIS project purge failed.") from error
