"""Real database queue limits, stale ownership, maintenance and worker recovery."""
import json
import sqlite3
from threading import Event,Thread
import pytest
from jobs import queue,worker
from storage import maintenance
from storage.database import _connect,create_project,StorageError


@pytest.fixture
def project(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"jobs.sqlite"))
    monkeypatch.setenv("GEOFATHOM_EXTERNAL_WORKER","1")
    return create_project("Worker contract")["id"]


def test_queue_request_bounds_and_terminal_cancel(project):
    with pytest.raises(StorageError,match="Unsupported"):
        queue.queue_job(project,"not-supported",{})
    with pytest.raises(StorageError,match="JSON object"):
        queue.queue_job(project,"export_geojson",[])
    with pytest.raises(StorageError,match="100 KB"):
        queue.queue_job(project,"export_geojson",{"large":"x"*100001})
    with pytest.raises(ValueError):
        queue.queue_job(project,"export_geojson",{"bad":float("nan")})
    jobs=[queue.queue_job(project,"export_geojson",{}) for _ in range(32)]
    with pytest.raises(StorageError,match="queue is full"):
        queue.queue_job(project,"export_geojson",{})
    uid=jobs[0]["id"]
    cancelled=queue.cancel_job(project,uid)
    assert cancelled["status"]=="cancelled" and cancelled["cancel_requested"]
    assert queue.cancel_job(project,uid)["status"]=="cancelled"
    assert queue.queue_job(project,"stac_ndvi",{})["payload"]["full_resolution"] is True
    assert len(queue.list_jobs(project,limit=40))==33
    stranger=create_project("Other project")["id"]
    for include in (True,False):
        with pytest.raises(StorageError,match="not found"):
            queue.get_job(stranger,uid,include_result=include)
    with pytest.raises(StorageError,match="not found"):
        queue.cancel_job(stranger,uid)


@pytest.mark.parametrize("poll,capacity",[(.01,2),(31,2),(1,0),(1,9)])
def test_external_worker_configuration_rejected(poll,capacity):
    with pytest.raises(ValueError,match="polling"):
        worker.run_worker(poll,max_workers=capacity)


def test_worker_survives_one_task_exception_without_losing_other_work(project,monkeypatch):
    first=queue.queue_job(project,"export_geojson",{})["id"]
    second=queue.queue_job(project,"export_geojson",{})["id"]
    # Ordering is deterministic despite the queue's timestamp resolution.
    with _connect() as db:
        db.execute("UPDATE gis_jobs SET created_at='2020-01-01 00:00:00' WHERE id=?",(first,))
        db.execute("UPDATE gis_jobs SET created_at='2020-01-01 00:00:01' WHERE id=?",(second,))
    stop=Event()
    finished=Event()
    seen=[]
    def task(uid,path):
        seen.append(uid)
        # A task fails after becoming terminal. The executor exception must
        # not terminate the polling process or replay completed work.
        status="failed" if uid==first else "completed"
        with sqlite3.connect(path) as db:
            db.execute("UPDATE gis_jobs SET status=? WHERE id=?",(status,uid))
        if uid==first:
            raise RuntimeError("injected worker exception")
        finished.set()
    monkeypatch.setattr(queue,"_worker",task)
    thread=Thread(target=worker.run_worker,args=(.05,stop,1))
    thread.start()
    try:
        assert finished.wait(10),seen
        assert thread.is_alive()
    finally:
        stop.set();thread.join(10)
    assert not thread.is_alive()
    assert seen==[first,second]
    assert queue.get_job(project,first)["status"]=="failed"
    assert queue.get_job(project,second)["status"]=="completed"


def test_worker_cleanup_only_prunes_terminal_rows(project):
    stale=queue.queue_job(project,"export_geojson",{})["id"]
    pending=queue.queue_job(project,"export_geojson",{})["id"]
    queue.cancel_job(project,stale)
    with _connect() as db:
        db.execute("UPDATE gis_jobs SET updated_at='2000-01-01T00:00:00+00:00' WHERE id IN (?,?)",(stale,pending))
    assert worker.cleanup(30)==1
    assert queue.get_job(project,pending)["status"]=="queued"
    with pytest.raises(StorageError,match="not found"):
        queue.get_job(project,stale)


def test_worker_cli_dispatches_validated_arguments(monkeypatch,capsys):
    import sys
    calls=[]
    monkeypatch.setattr(worker,"cleanup",lambda days:calls.append(days) or 3)
    monkeypatch.setattr(sys,"argv",["worker","--cleanup-days","30"])
    worker.main()
    assert calls==[30] and "Removed 3" in capsys.readouterr().out
    def interrupt(poll,max_workers):
        calls.append((poll,max_workers))
        raise KeyboardInterrupt
    monkeypatch.setattr(worker,"run_worker",interrupt)
    monkeypatch.setattr(sys,"argv",["worker","--poll","0.5","--workers","4"])
    worker.main()
    assert calls[-1]==(.5,4)


def test_maintenance_cli_and_rotation_keep_verified_snapshots(project,monkeypatch,tmp_path,capsys):
    import sys
    directory=tmp_path/"backups";directory.mkdir()
    other=directory/"geofathom-manual.sqlite";other.write_bytes(b"manual")
    old=maintenance.backup_rotation(directory,1)["backup"]
    newer=maintenance.backup_rotation(directory,1)
    from pathlib import Path
    assert not Path(old).exists()
    assert Path(newer["backup"]).is_file() and other.read_bytes()==b"manual"
    restored=tmp_path/"restored.sqlite"
    monkeypatch.setattr(sys,"argv",["maintenance","--restore-from",newer["backup"],
        "--restore-to",str(restored),"--verify"])
    maintenance.main()
    outcome=json.loads(capsys.readouterr().out)
    assert outcome["restored"]==str(restored.resolve())
    assert outcome["spatial_index"]["missing_before"]==0
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT id FROM projects").fetchone()[0]==project
    monkeypatch.setattr(sys,"argv",["maintenance","--interval","30"])
    with pytest.raises(SystemExit) as e:maintenance.main()
    assert e.value.code==2


def test_temporary_backup_path_and_restore_collision_never_overwrite(project,tmp_path):
    dest=tmp_path/"backup.sqlite"
    temp=dest.with_suffix(".sqlite.tmp");temp.write_bytes(b"existing")
    with pytest.raises(ValueError,match="Temporary"):
        maintenance.backup_database(dest)
    assert temp.read_bytes()==b"existing" and not dest.exists()
    temp.unlink()
    backup=maintenance.backup_database(dest)
    occupied=tmp_path/"occupied.sqlite";occupied.write_bytes(b"untouched")
    with pytest.raises(ValueError,match="already exists"):
        maintenance.restore_to_new_database(backup,occupied)
    assert occupied.read_bytes()==b"untouched"
