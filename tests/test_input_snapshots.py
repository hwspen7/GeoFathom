"""Execution snapshots retain the exact bytes used by local analysis."""
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from storage.snapshots import analysis_snapshot,copy_verified
from imagery.store import image_file


def test_snapshot_survives_source_replacement_and_cleans_up(tmp_path,monkeypatch):
    library=tmp_path/"imagery"
    library.mkdir()
    scratch=tmp_path/"scratch"
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(library))
    monkeypatch.setenv("GEOFATHOM_SNAPSHOT_DIR",str(scratch))
    uid=str(uuid4())
    path=library/(uid+".tif")
    path.write_bytes(b"original")
    with analysis_snapshot("spectral_index",{"image_id":uid}) as provenance:
        frozen=image_file(uid)
        assert frozen!=path
        assert frozen.read_bytes()==b"original"
        assert provenance["source_sha256"][uid]==sha256(b"original").hexdigest()
        path.write_bytes(b"updated")
        assert image_file(uid).read_bytes()==b"original"
    assert image_file(uid).read_bytes()==b"updated"
    assert not frozen.exists()
    assert list(scratch.iterdir())==[]


def test_snapshot_checksum_and_failed_task_cleanup(tmp_path,monkeypatch):
    library=tmp_path/"imagery"
    library.mkdir()
    scratch=tmp_path/"scratch"
    monkeypatch.setenv("GEOFATHOM_IMAGERY_DIR",str(library))
    monkeypatch.setenv("GEOFATHOM_SNAPSHOT_DIR",str(scratch))
    uid=str(uuid4())
    source=library/(uid+".tif")
    source.write_bytes(b"123")
    with pytest.raises(RuntimeError,match="failed"):
        with analysis_snapshot("spectral_index",{"image_id":uid}):
            raise RuntimeError("failed")
    assert list(scratch.iterdir())==[]
    assert copy_verified(source,tmp_path/"copy")==sha256(b"123").hexdigest()
