from storage.database import create_project
from storage.maintenance import backup_rotation

def test_rotating_backups_keep_only_owned_snapshots(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"main.sqlite"))
    create_project("archive")
    directory=tmp_path/"backup";directory.mkdir()
    outside=directory/"unrelated.sqlite";outside.write_bytes(b"keep")
    for _ in range(4):backup_rotation(directory,retain=2)
    assert len(list(directory.glob("geofathom-*.sqlite")))==2
    assert outside.read_bytes()==b"keep"
