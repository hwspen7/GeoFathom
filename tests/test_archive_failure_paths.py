"""Real filesystem and SQLite corruption checks, no simulated success."""
import hashlib
import sqlite3
from pathlib import Path
import pytest
from storage import versions,incremental
from storage.database import create_project,database_path


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"live.sqlite"))


def test_archive_verify_corrupt_source_and_materialized_output(tmp_path):
    source=tmp_path/"image";source.write_bytes(b"original")
    digest=hashlib.sha256(b"original").hexdigest()
    root=tmp_path/"archive"
    path=versions.publish(root,source,digest)
    assert versions.publish(root,source,digest)==path
    output=tmp_path/"output"
    versions.materialize(root,digest,output)
    assert output.read_bytes()==b"original"
    path.write_bytes(b"altered")
    with pytest.raises(RuntimeError,match="content address"):
        versions.publish(root,source,digest)
    output.unlink()
    with pytest.raises(RuntimeError,match="SHA-256"):
        versions.materialize(root,digest,output)
    assert not output.exists()
    path.unlink()
    with pytest.raises(RuntimeError,match="missing"):
        versions.materialize(root,digest,output)
    with pytest.raises(RuntimeError,match="differs"):
        versions.publish(root,source,"0"*64)
    with pytest.raises(ValueError,match="address"):
        versions.object_path(root,"../escape")


def test_archive_concurrent_publish_and_model_filename(monkeypatch,tmp_path):
    source=tmp_path/"input";source.write_bytes(b"data")
    root=tmp_path/"archive";digest=hashlib.sha256(b"data").hexdigest()
    link=versions.os.link
    def racing(a,b):
        link(a,b)
        raise FileExistsError
    monkeypatch.setattr(versions.os,"link",racing)
    assert versions.publish(root,source,digest).read_bytes()==b"data"
    with pytest.raises(ValueError,match="filename"):
        versions.archive_inputs(root,{"source_sha256":{},"model_files_sha256":{"../x":digest}})


@pytest.mark.parametrize("retain",[False,0,366])
def test_invalid_retention(tmp_path,retain):
    with pytest.raises(ValueError,match="Retention"):
        incremental.capture(tmp_path/"archive.sqlite",retain)


def test_incremental_archive_rejects_live_database_and_missing_generations(tmp_path):
    create_project("backup project")
    archive=tmp_path/"archive.sqlite"
    with pytest.raises(ValueError,match="differ"):
        incremental.generations(database_path())
    with pytest.raises(FileNotFoundError):
        incremental.restore(archive,"missing",tmp_path/"out.sqlite")
    incremental.capture(archive)
    with pytest.raises(ValueError,match="does not exist"):
        incremental.restore(archive,"missing",tmp_path/"out.sqlite")


@pytest.mark.parametrize("damage",["size","digest","chunk","ordinal"])
def test_incremental_restore_detects_corruption_before_publish(tmp_path,damage):
    create_project("backup project")
    archive=tmp_path/"archive.sqlite"
    generation=incremental.capture(archive)["generation"]
    with sqlite3.connect(archive) as db:
        if damage=="size":
            db.execute("UPDATE archive_generations SET bytes=0")
        elif damage=="digest":
            db.execute("UPDATE archive_generations SET digest='bad'")
        elif damage=="chunk":
            db.execute("UPDATE archive_chunks SET content=x'00'")
        else:
            db.execute("UPDATE archive_manifest SET ordinal=ordinal+1000")
    output=tmp_path/"restored.sqlite"
    with pytest.raises(RuntimeError):
        incremental.restore(archive,generation,output)
    assert not output.exists()
