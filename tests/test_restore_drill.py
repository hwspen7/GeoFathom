import sqlite3
from pathlib import Path
import pytest
from storage.database import create_project,add_features
from storage.maintenance import backup_database,restore_to_new_database

def test_restore_drill_preserves_project_features_and_rejects_overwrite(tmp_path,monkeypatch):
    source=tmp_path/"current.sqlite"
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(source))
    project=create_project("Recovery")["id"]
    add_features(project,[{"name":"A","geometry":{"type":"Point","coordinates":[10,20]}}])
    backup=Path(backup_database(tmp_path/"backup.sqlite"))
    dest=tmp_path/"restored.sqlite"
    result=restore_to_new_database(backup,dest)
    assert result==str(dest.resolve())
    with sqlite3.connect(dest) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert conn.execute("SELECT id FROM projects").fetchone()[0]==project
        assert conn.execute("SELECT count(*) FROM features").fetchone()[0]==1
    with pytest.raises(ValueError,match="exists"):
        restore_to_new_database(backup,dest)
    corrupt=tmp_path/"bad.sqlite";corrupt.write_bytes(b"not SQLite")
    with pytest.raises((sqlite3.DatabaseError,RuntimeError)):
        restore_to_new_database(corrupt,tmp_path/"bad-restored.sqlite")
    assert not (tmp_path/"bad-restored.sqlite").exists()
