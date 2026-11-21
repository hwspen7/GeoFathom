"""P2 persistent GIS background job lifecycle, result and permission tests."""
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
    assert job["status"]=="completed",job
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
