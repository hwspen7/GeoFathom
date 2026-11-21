"""Transactional SQLite storage for local geospatial projects.

The database is deliberately separated from GIS operations and model providers.
Use a configured writable path; local deployments default to data/geofathom.sqlite.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from geometry.measure import GeometryError, measure_geometry

_ROOT = Path(__file__).resolve().parent.parent


class StorageError(ValueError):
    """A user input, missing record, or project conflict."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path() -> Path:
    return Path(os.getenv("GEOFATHOM_DATABASE_PATH", str(_ROOT / "data" / "geofathom.sqlite"))).expanduser()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS features (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                geometry TEXT NOT NULL,
                properties TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS features_project_id_idx ON features(project_id);
            """
        )
        # Keep spatial-index SQLite UDFs registered on every writer connection;
        # INSERT/UPDATE triggers call them even outside spatial queries.
        from .paging import prepare_rtree
        prepare_rtree(connection)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _required_project(connection: sqlite3.Connection, project_id: str) -> dict:
    row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise StorageError("Project not found.")
    return dict(row)


def create_project(name: str, description: str = "") -> dict:
    timestamp = _now()
    record = {
        "id": str(uuid4()), "name": name.strip(),
        "description": description.strip(), "created_at": timestamp,
        "updated_at": timestamp,
    }
    with _connect() as connection:
        connection.execute(
            "INSERT INTO projects VALUES (:id, :name, :description, :created_at, :updated_at)",
            record,
        )
    return record


def list_projects(limit: int = 100, offset: int = 0) -> dict:
    with _connect() as connection:
        total = connection.execute("SELECT count(*) FROM projects").fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"results": [dict(row) for row in rows], "total": total}


def get_project(project_id: str) -> dict:
    with _connect() as connection:
        return _required_project(connection, project_id)


def delete_project(project_id: str) -> None:
    with _connect() as connection:
        _required_project(connection, project_id)
        connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def _record_feature(
    connection: sqlite3.Connection, project_id: str, geometry: dict,
    name: str, source: str, properties: dict,
) -> dict:
    measurement = measure_geometry(geometry)
    feature_id = str(uuid4())
    timestamp = _now()
    connection.execute(
        """INSERT INTO features (id, project_id, name, geometry, properties, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            feature_id, project_id, name, json.dumps(geometry, allow_nan=False),
            json.dumps(properties, allow_nan=False), source, timestamp,
        ),
    )
    return {
        "id": feature_id, "project_id": project_id, "name": name,
        "geometry": geometry, "properties": properties,
        "source": source, "created_at": timestamp, "measurement": measurement,
    }


def add_features(project_id: str, inputs: list[dict[str, Any]]) -> dict:
    if not 1 <= len(inputs) <= 100:
        raise StorageError("Submit between 1 and 100 geographic features.")
    with _connect() as connection:
        _required_project(connection, project_id)
        results = []
        for feature in inputs:
            geometry = feature.get("geometry")
            name = str(feature.get("name") or "Untitled feature").strip()[:200]
            source = str(feature.get("source") or "User supplied").strip()[:200]
            properties = feature.get("properties", {})
            if not isinstance(properties, dict):
                raise StorageError("Feature properties must be an object.")
            if len(json.dumps(properties, allow_nan=False)) > 100_000:
                raise StorageError("Feature properties are too large.")
            try:
                results.append(
                    _record_feature(connection, project_id, geometry, name, source, properties)
                )
            except (GeometryError, ValueError, TypeError) as error:
                raise StorageError(str(error)) from error
        connection.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?", (_now(), project_id)
        )
    return {"results": results, "created": len(results)}


def list_features(project_id: str, limit: int = 200, offset: int = 0) -> dict:
    with _connect() as connection:
        _required_project(connection, project_id)
        total = connection.execute(
            "SELECT count(*) FROM features WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        rows = connection.execute(
            """SELECT * FROM features WHERE project_id = ?
               ORDER BY created_at, id LIMIT ? OFFSET ?""",
            (project_id, limit, offset),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["geometry"] = json.loads(item["geometry"])
        item["properties"] = json.loads(item["properties"])
        item["measurement"] = measure_geometry(item["geometry"])
        results.append(item)
    return {"results": results, "total": total}


def delete_feature(project_id: str, feature_id: str) -> None:
    with _connect() as connection:
        _required_project(connection, project_id)
        result = connection.execute(
            "DELETE FROM features WHERE id = ? AND project_id = ?", (feature_id, project_id)
        )
        if not result.rowcount:
            raise StorageError("Feature not found.")
        connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (_now(), project_id))


def export_project(project_id: str) -> dict:
    with _connect() as connection:
        _required_project(connection, project_id)
        rows = connection.execute(
            "SELECT * FROM features WHERE project_id = ? ORDER BY created_at, id",
            (project_id,),
        ).fetchall()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": row["id"],
                "geometry": json.loads(row["geometry"]),
                "properties": {
                    **json.loads(row["properties"]),
                    "name": row["name"],
                    "source": row["source"],
                },
            }
            for row in rows
        ],
    }
