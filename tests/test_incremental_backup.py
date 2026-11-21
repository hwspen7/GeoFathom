"""Actual SQLite snapshot deduplication, retention and corruption recovery."""
import sqlite3
import pytest
from storage.database import create_project,add_features
from storage.incremental import capture,generations,restore

def test_incremental_backup_dedup_and_historical_restore(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"live.sqlite"))
    project=create_project("Incremental")["id"]
    archive=tmp_path/"archive.sqlite"
    first=capture(archive,retain=3)
    second=capture(archive,retain=3)
    assert first["snapshot_bytes"]==first["new_chunk_bytes"]
    assert second["new_chunk_bytes"]==0
    assert first["sha256"]==second["sha256"]
    add_features(project,[{"name":"A","geometry":{"type":"Point","coordinates":[1,2]}}])
    third=capture(archive,retain=2)
    assert {x["id"] for x in generations(archive)}=={second["generation"],third["generation"]}
    for row,count in [(second,0),(third,1)]:
        destination=tmp_path/(row["generation"]+".sqlite")
        restore(archive,row["generation"],destination)
        with sqlite3.connect(destination) as conn:
            assert conn.execute("SELECT count(*) FROM features").fetchone()[0]==count
            assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    with sqlite3.connect(archive) as db:
        assert db.execute("""SELECT count(*) FROM archive_chunks c WHERE NOT EXISTS
            (SELECT 1 FROM archive_manifest m WHERE m.digest=c.digest)""").fetchone()[0]==0
        db.execute("UPDATE archive_chunks SET content=x'00'")
    destination=tmp_path/"corrupt.sqlite"
    with pytest.raises(RuntimeError,match="corrupt"):
        restore(archive,third["generation"],destination)
    assert not destination.exists()

def test_incremental_large_database_stores_only_changed_chunks(tmp_path,monkeypatch):
    live=tmp_path/"live.sqlite"
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(live))
    create_project("Large")
    with sqlite3.connect(live) as db:
        db.execute("CREATE TABLE test_payload(id INTEGER PRIMARY KEY, data BLOB)")
        db.executemany("INSERT INTO test_payload(data) VALUES(?)",[(b"x"*65536,)]*64)
    archive=tmp_path/"archive.sqlite"
    start=capture(archive)
    with sqlite3.connect(live) as db:
        db.execute("UPDATE test_payload SET data=? WHERE id=32",(b"y"*65536,))
    delta=capture(archive)
    assert 0<delta["new_chunk_bytes"]<start["snapshot_bytes"]//2
    dst=tmp_path/"recovered.sqlite"
    restore(archive,delta["generation"],dst)
    with sqlite3.connect(dst) as db:
        assert db.execute("SELECT data FROM test_payload WHERE id=32").fetchone()[0]==b"y"*65536
