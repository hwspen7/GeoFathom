"""SQLite local storage initialization and trigger maintenance regressions."""
import json
import sqlite3

import pytest

from storage.database import _connect,create_project,add_features
from storage import paging


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"schema.sqlite"))


def test_schema_initializes_once_but_bbox_triggers_work_on_new_connections(
        monkeypatch):
    calls=[]
    original=paging.prepare_rtree
    def spy(connection):
        calls.append(1)
        return original(connection)
    monkeypatch.setattr(paging,"prepare_rtree",spy)
    project=create_project("Indexed workspace")["id"]
    for position in ((10.,20.),(12.,22.),(14.,24.)):
        add_features(project,[{
            "name":"Point",
            "geometry":{"type":"Point","coordinates":list(position)},
        }])
    with _connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0]==1
        assert connection.execute(
            "SELECT count(*) FROM feature_bounds").fetchone()[0]==3
        assert connection.execute(
            "SELECT count(*) FROM features").fetchone()[0]==3
    for _ in range(10):
        with _connect() as connection:
            assert connection.execute("SELECT count(*) FROM projects").fetchone()[0]==1
    assert len(calls)==1


def test_existing_legacy_schema_is_backfilled_exactly_once(monkeypatch,tmp_path):
    db=tmp_path/"legacy.sqlite"
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(db))
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL);
            CREATE TABLE features(id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,geometry TEXT NOT NULL,properties TEXT NOT NULL,
                source TEXT NOT NULL,created_at TEXT NOT NULL);
        """)
        connection.execute("INSERT INTO projects VALUES('p','Legacy','','now','now')")
        connection.execute("INSERT INTO features VALUES(?,?,?,?,?,?,?)",
           ("f","p","Legacy point",
            json.dumps({"type":"Point","coordinates":[10.,20.]}),
            "{}","user","now"))
    with _connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0]==1
        assert connection.execute("SELECT count(*) FROM feature_bounds").fetchone()[0]==1
    with _connect() as connection:
        row=connection.execute("SELECT minx,maxy FROM feature_bounds").fetchone()
        assert tuple(row)==(10.,20.)
