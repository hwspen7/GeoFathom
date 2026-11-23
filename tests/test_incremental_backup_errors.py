"""Explicit failure-path acceptance for incremental SQLite database archival."""
import sqlite3

import pytest

from storage import incremental
from storage.database import create_project


@pytest.fixture
def archive(tmp_path,monkeypatch):
    live=tmp_path/"live.sqlite"
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(live))
    create_project("Corruption verification")
    path=tmp_path/"backup.sqlite"
    first=incremental.capture(path,retain=4)
    return live,path,first


@pytest.mark.parametrize("retain",[0,-1,366,True,False,1.5,"7"])
def test_capture_rejects_invalid_retention_without_touching_archive(tmp_path,retain):
    path=tmp_path/"backup.sqlite"
    with pytest.raises(ValueError,match="Retention"):
        incremental.capture(path,retain=retain)
    assert not path.exists()


def test_backup_archive_must_not_reuse_live_database_path(archive):
    live,_,_=archive
    with pytest.raises(ValueError,match="differ"):
        incremental._open(live)


def test_restore_rejects_missing_archive_and_unknown_generation(archive,tmp_path):
    _,path,first=archive
    with pytest.raises(FileNotFoundError,match="missing"):
        incremental.restore(tmp_path/"missing.sqlite",first["generation"],tmp_path/"target.sqlite")
    with pytest.raises(ValueError,match="does not exist"):
        incremental.restore(path,"missing-version",tmp_path/"target.sqlite")
    assert not (tmp_path/"target.sqlite").exists()


@pytest.mark.parametrize("corruption,expected",[
    ("missing_chunk","snapshot failed"),
    ("reordered","corrupt or missing"),
    ("altered_chunk","corrupt or missing"),
    ("wrong_snapshot_digest","snapshot failed"),
    ("wrong_snapshot_length","corrupt or missing"),
    ("zero_snapshot_length","Invalid snapshot length"),
])
def test_restore_fails_closed_on_each_manifest_corruption(
    archive,tmp_path,corruption,expected,
):
    _,path,generation=archive
    with sqlite3.connect(path) as db:
        if corruption=="missing_chunk":
            db.execute("DELETE FROM archive_manifest WHERE generation=? AND ordinal=0",
                       (generation["generation"],))
        elif corruption=="reordered":
            db.execute("UPDATE archive_manifest SET ordinal=ordinal+200 WHERE generation=? AND ordinal=0",
                       (generation["generation"],))
        elif corruption=="altered_chunk":
            db.execute("UPDATE archive_chunks SET content=x'00' WHERE digest IN (SELECT digest FROM archive_manifest WHERE generation=? LIMIT 1)",
                       (generation["generation"],))
        elif corruption=="wrong_snapshot_digest":
            db.execute("UPDATE archive_generations SET digest=? WHERE id=?",
                       ("0"*64,generation["generation"]))
        elif corruption=="wrong_snapshot_length":
            db.execute("UPDATE archive_generations SET bytes=bytes+1 WHERE id=?",
                       (generation["generation"],))
        elif corruption=="zero_snapshot_length":
            db.execute("UPDATE archive_generations SET bytes=0 WHERE id=?",
                       (generation["generation"],))
    dest=tmp_path/"tampered-output.sqlite"
    with pytest.raises(RuntimeError,match=expected):
        incremental.restore(path,generation["generation"],dest)
    assert not dest.exists()


def test_corrupted_deduplicated_chunk_is_rejected_before_new_generation(archive):
    _,path,first=archive
    with sqlite3.connect(path) as db:
        db.execute("UPDATE archive_chunks SET content=x'00'")
    with pytest.raises(RuntimeError,match="Existing backup chunk"):
        incremental.capture(path)
    assert len(incremental.generations(path))==1
    assert incremental.generations(path)[0]["id"]==first["generation"]


def test_capture_rejects_source_snapshot_beyond_configured_size_limit(
    archive,monkeypatch,
):
    _,path,_=archive
    monkeypatch.setattr(incremental,"MAX_BYTES",1)
    with pytest.raises(ValueError,match="size limit"):
        incremental.capture(path)
