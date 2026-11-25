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
        assert connection.execute("PRAGMA user_version").fetchone()[0]==2
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
        assert connection.execute("PRAGMA user_version").fetchone()[0]==2
        assert connection.execute("SELECT count(*) FROM feature_bounds").fetchone()[0]==1
    with _connect() as connection:
        row=connection.execute("SELECT minx,maxy FROM feature_bounds").fetchone()
        assert tuple(row)==(10.,20.)

def test_numbered_migration_and_future_version_rejection(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/"migration.sqlite"
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(path))
    create_project("Old")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=1")
    def open_version(_):
        with _connect() as db:
            return db.execute("PRAGMA user_version").fetchone()[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(open_version,range(8)))==[2]*8
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM gf_migrations WHERE version=2").fetchone()[0]==1
        db.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError,match="newer"):
        with _connect():
            pass


def test_concurrent_cold_start_creates_every_project_and_index(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from core.main import app
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","local")
    barrier=Barrier(16)
    def create(i):
        with TestClient(app,raise_server_exceptions=True) as client:
            barrier.wait(timeout=15)
            result=client.post("/projects",json={"name":f"Cold start {i}"})
            assert result.status_code==201,result.text
            uid=result.json()["id"]
            point=client.post(f"/projects/{uid}/features",json={
                "name":"Point","source":"test",
                "geometry":{"type":"Point","coordinates":[i,20]}})
            assert point.status_code==201,point.text
            return uid
    with ThreadPoolExecutor(max_workers=16) as pool:
        ids=list(pool.map(create,range(16)))
    assert len(set(ids))==16
    with _connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==2
        assert db.execute("PRAGMA journal_mode").fetchone()[0]=="wal"
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0]==16
        assert db.execute("SELECT count(*) FROM feature_bounds").fetchone()[0]==16
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_failed_bootstrap_rolls_back_schema_and_can_retry(monkeypatch):
    original=paging.prepare_rtree
    def fail(connection):
        original(connection)
        raise RuntimeError("injected initialization failure")
    monkeypatch.setattr(paging,"prepare_rtree",fail)
    with pytest.raises(RuntimeError,match="injected initialization"):
        create_project("Uncommitted")
    from storage.database import database_path
    with sqlite3.connect(database_path()) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==0
        assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('projects','features','feature_bounds')").fetchall()
    monkeypatch.setattr(paging,"prepare_rtree",original)
    assert create_project("Recovered")["name"]=="Recovered"
