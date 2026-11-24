"""Research persistent GIS background job lifecycle, result and permission tests."""
import time

import pytest
from fastapi.testclient import TestClient
from core.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def tmp(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"jobs.sqlite"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN","admin-for-test")


def setup():
    response=client.post("/projects",json={"name":"Background GIS"})
    assert response.status_code==201,response.text
    return "/projects/"+response.json()["id"]


def finished(root,job_id,timeout=8):
    until=time.monotonic()+timeout
    last=None
    while time.monotonic()<until:
        r=client.get(root+"/jobs/"+job_id)
        assert r.status_code==200,r.text
        last=r.json()
        if last["status"] in {"completed","cancelled","failed","interrupted"}:
            return last
        time.sleep(.03)
    raise AssertionError(f"Job not terminal after {timeout}s: {last}")


def test_export_job_persists_result_and_downloads_real_geojson():
    root=setup()
    r=client.post(root+"/features",json={
        "name":"Feature A","geometry":{"type":"Point","coordinates":[-83,40]},
        "properties":{"category":"site"},
    })
    assert r.status_code==201,r.text
    response=client.post(root+"/jobs",json={"kind":"export_geojson","payload":{}})
    assert response.status_code==202,response.text
    uid=response.json()["id"]
    job=finished(root,uid)
    assert job["status"]=="completed",job
    assert job["progress"]==100
    assert job["result"]["type"]=="FeatureCollection"
    assert job["result"]["features"][0]["properties"]["name"]=="Feature A"
    download=client.get(root+"/jobs/"+uid+"/download")
    assert download.status_code==200,download.text
    assert download.headers["content-type"].startswith("application/geo+json")
    assert download.json()["features"][0]["geometry"]["coordinates"]==[-83,40]
    assert client.get(root+"/jobs").json()["jobs"][0]["id"]==uid


def test_topology_qa_and_spatial_selection_execute_background():
    root=setup()
    geom={"type":"Polygon","coordinates":[[
        [0,0],[.03,0],[.03,.03],[0,.03],[0,0],
    ]]}
    assert client.post(root+"/features",json={
        "name":"Field","geometry":geom,
    }).status_code==201
    for kind,payload in (
        ("topology_qa",{}),
        ("spatial_select",{"geometry":geom,"relation":"intersects"}),
    ):
        queued=client.post(root+"/jobs",json={"kind":kind,"payload":payload})
        assert queued.status_code==202,queued.text
        job=finished(root,queued.json()["id"])
        assert job["status"]=="completed",job
        if kind=="spatial_select":
            assert job["result"]["total"]==1


def test_invalid_task_marks_failed_with_error_and_keeps_project_data():
    root=setup()
    queued=client.post(root+"/jobs",json={
        "kind":"spatial_select","payload":{"relation":"intersects"},
    })
    assert queued.status_code==202
    job=finished(root,queued.json()["id"])
    assert job["status"]=="failed"
    assert isinstance(job["error"],str) and job["error"]
    assert client.get(root+"/workspace").json()["total"]==0


def test_admin_required_for_powerful_jobs():
    root=setup()
    for kind in ("rebuild_index","postgis_sync"):
        no=client.post(root+"/jobs",json={"kind":kind,"payload":{}})
        assert no.status_code==403
    authorized=client.post(root+"/jobs",json={
        "kind":"rebuild_index","payload":{},
    },headers={"X-GeoFathom-Admin-Token":"admin-for-test"})
    assert authorized.status_code==202,authorized.text
    job=finished(root,authorized.json()["id"])
    assert job["status"]=="completed",job.get("error")
    assert job["result"]["indexed_features"]==0


def test_project_scope_and_wrong_ids_rejected():
    root=setup();other=setup()
    queued=client.post(root+"/jobs",json={"kind":"export_geojson"}).json()
    assert client.get(other+"/jobs/"+queued["id"]).status_code==404
    assert client.get(other+"/jobs/"+queued["id"]+"/download").status_code==404
    assert client.post(other+"/jobs/"+queued["id"]+"/cancel").status_code==404
    assert client.get(root+"/jobs/no-such-job").status_code==404


def test_job_cancellation_never_reports_false_completed_result(monkeypatch):
    from jobs import queue
    root=setup()
    original=queue._execute
    def slow(kind,project_id,payload):
        time.sleep(.2)
        return original(kind,project_id,payload)
    monkeypatch.setattr(queue,"_execute",slow)
    created=client.post(root+"/jobs",json={"kind":"export_geojson"}).json()
    cancelled=client.post(root+"/jobs/"+created["id"]+"/cancel")
    assert cancelled.status_code==200
    result=finished(root,created["id"])
    assert result["status"]=="cancelled",result
    assert result["result"] is None


def test_payload_bounds_and_no_credentials_in_job_response():
    root=setup()
    assert client.post(root+"/jobs",json={
        "kind":"unknown","payload":{},
    }).status_code==422
    large=client.post(root+"/jobs",json={
        "kind":"topology_qa","payload":{"comment":"x"*110000},
    })
    assert large.status_code==422

def test_cancelled_running_job_does_not_become_failed_on_worker_exception(monkeypatch):
    from threading import Event
    from jobs import queue
    root=setup()
    started=Event()
    release=Event()

    def blocked_failure(kind,project_id,payload):
        started.set()
        assert release.wait(4), "Test worker was never released"
        raise RuntimeError("Simulated provider interruption after cancellation")

    monkeypatch.setattr(queue,"_execute",blocked_failure)
    try:
        created=client.post(root+"/jobs",json={"kind":"export_geojson"}).json()
        assert started.wait(4), "Queued job did not start"
        request=client.post(root+"/jobs/"+created["id"]+"/cancel")
        assert request.status_code==200,request.text
    finally:
        release.set()
    result=finished(root,created["id"])
    assert result["status"]=="cancelled",result
    assert result["result"] is None
    assert result["error"] is None


def test_large_results_are_not_loaded_into_background_polling(monkeypatch):
    from jobs import queue
    from storage.database import _connect
    root=setup()
    monkeypatch.setattr(queue,"_execute",
                        lambda kind,project_id,payload:{"payload":"x"*1_000_000})
    job=client.post(root+"/jobs",
                    json={"kind":"export_geojson","payload":{}}).json()
    uid=job["id"]
    completed=finished(root,uid)
    assert completed["result"]["payload"]=="x"*1_000_000
    metadata=client.get(root+"/jobs")
    assert metadata.status_code==200
    assert len(metadata.content)<5_000
    assert metadata.json()["jobs"][0]["has_result"] is True
    assert metadata.json()["jobs"][0]["result"] is None
    lightweight=client.get(root+"/jobs/"+uid+"?include_result=false").json()
    assert lightweight["has_result"] is True and lightweight["result"] is None
    assert client.get(root+"/jobs/"+uid).json()["result"]==completed["result"]
    with _connect() as connection:
        assert connection.execute(
            "SELECT result FROM gis_jobs WHERE id=?",(uid,)).fetchone()[0] is None
        saved=connection.execute(
            "SELECT size_bytes FROM gis_job_results WHERE job_id=?",(uid,)).fetchone()[0]
        assert saved>1_000_000


def test_progress_throttles_database_connections_and_honors_cancel():
    import time
    from jobs import queue
    from contextlib import contextmanager
    from storage.database import _connect
    root=setup()
    uid=client.post(root+"/jobs",json={"kind":"export_geojson"}).json()["id"]
    finished(root,uid)
    visits=[]
    original=queue._job_db
    @contextmanager
    def spy():
        visits.append(1)
        with original() as db:
            yield db
    queue._job_db=spy
    state={"value":10,"checked":time.monotonic(),"committed":time.monotonic()}
    token=queue._ACTIVE_JOB.set(uid)
    statetoken=queue._ACTIVE_PROGRESS.set(state)
    try:
        for _ in range(1000):
            queue._progress(.01)
        assert len(visits)==0
        queue._progress(.3)
        assert len(visits)==1
    finally:
        queue._ACTIVE_PROGRESS.reset(statetoken)
        queue._ACTIVE_JOB.reset(token)
        queue._job_db=original
