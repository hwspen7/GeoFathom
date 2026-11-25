"""SQLite online backup, partial spatial-index repair, and retention."""
import sqlite3

import pytest

from storage.database import _connect,create_project,add_features
from storage.maintenance import backup_database,verify_spatial_indexes


@pytest.fixture(autouse=True)
def local_db(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"working.sqlite"))


def test_consistent_sqlite_backup_and_restore_without_copying_wal(tmp_path):
    project=create_project("Backup")["id"]
    add_features(project,[{"geometry":{"type":"Point","coordinates":[10,20]},
                           "name":"A"}])
    dest=tmp_path/"snapshot.sqlite"
    assert backup_database(dest)==str(dest.resolve())
    assert dest.is_file()
    with sqlite3.connect(dest) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert conn.execute("SELECT count(*) FROM features").fetchone()[0]==1
        assert conn.execute("PRAGMA user_version").fetchone()[0]>=1
    with pytest.raises(ValueError,match="differ"):
        from storage.database import database_path
        backup_database(database_path())


def test_detect_and_repair_partial_rtree_corruption():
    project=create_project("Index QA")["id"]
    add_features(project,[{"geometry":{
        "type":"Point","coordinates":[float(x),20.0]},
        "name":"Target"} for x in range(3)])
    assert verify_spatial_indexes()=={
        "missing_before":0,"extra_before":0,
        "missing_after":0,"extra_after":0,"repaired":False}
    with _connect() as c:
        c.execute("DELETE FROM feature_bounds WHERE feature_rowid IN "
                  "(SELECT rowid FROM features ORDER BY rowid LIMIT 1)")
    state=verify_spatial_indexes()
    assert state["missing_before"]==1
    assert state["repaired"] is False
    repaired=verify_spatial_indexes(repair=True)
    assert repaired["missing_before"]==1
    assert repaired["missing_after"]==0
    assert verify_spatial_indexes()["missing_after"]==0


def test_backup_missing_source_does_not_create_empty_database(tmp_path):
    from storage.database import database_path
    dest = tmp_path / "backup.sqlite"
    with pytest.raises(ValueError, match="does not exist"):
        backup_database(dest)
    assert not database_path().exists() and not dest.exists()


def test_restore_rejects_unrelated_sqlite_and_cleans_destination(tmp_path):
    from storage.maintenance import restore_to_new_database
    source = tmp_path / "unrelated.sqlite"
    conn = sqlite3.connect(source)
    try:
        conn.execute("CREATE TABLE unrelated(value)")
        conn.commit()
    finally:
        conn.close()
    dest = tmp_path / "restored.sqlite"
    with pytest.raises(RuntimeError, match="not a GeoFathom"):
        restore_to_new_database(source, dest)
    assert not dest.exists()


def test_audit_imagery_keeps_scanning_after_bad_sidecar(monkeypatch, tmp_path):
    from storage.maintenance import audit_imagery
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR", str(tmp_path))
    for name in ("bad", "mismatch"):
        (tmp_path / (name + ".tif")).write_bytes(b"sample")
    (tmp_path / "bad.json").write_text("{broken")
    (tmp_path / "mismatch.json").write_text('{"sha256":"incorrect"}')
    (tmp_path / "missing.json").write_text("{}")
    report = audit_imagery()
    assert report["checked"] == 2
    assert set(report["mismatches"]) == {"bad:invalid-sidecar", "mismatch:sha256-mismatch", "missing:missing-image"}
