"""Linked topology previews and atomic multi-feature edits."""
import pytest
from fastapi.testclient import TestClient
from core.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"topology.sqlite"))


def polygon(x1,x2):
    return {"type":"Polygon","coordinates":[[[x1,0],[x2,0],[x2,.01],[x1,.01],[x1,0]]]}


def data():
    project=client.post("/projects",json={"name":"Shared topology"}).json()
    base="/projects/"+project["id"]
    features=[]
    for a,b in [(0,.01),(.01,.02)]:
        result=client.post(base+"/features",json={"name":"Plot","geometry":polygon(a,b),"source":"Test"})
        assert result.status_code==201,result.text
        features.append(result.json()["id"])
    return base,features


def test_shared_vertex_moves_both_geometries_and_versions():
    base,features=data()
    coordinates={"old":[.01,0],"new":[.0105,-.0001],"tolerance_m":.05}
    preview=client.post(base+"/topology/preview",json=coordinates)
    assert preview.status_code==200,preview.text
    assert preview.json()["count"]==2
    expected={x["id"]:x["revision"] for x in preview.json()["affected"]}
    applied=client.post(base+"/topology/move",json={
        **coordinates,"expected_revisions":expected})
    assert applied.status_code==200,applied.text
    assert applied.json()["count"]==2
    updated=client.get(base+"/workspace").json()["features"]
    assert all(x["revision"]==1 for x in updated)
    for item in updated:
        assert [.0105,-.0001] in item["geometry"]["coordinates"][0]


def test_shared_vertex_rolls_back_when_layer_locked():
    base,features=data()
    preview=client.post(base+"/topology/preview",json={
        "old":[.01,0],"new":[.0105,-.0001]}).json()
    expected={x["id"]:x["revision"] for x in preview["affected"]}
    layer=client.post(base+"/layers",json={"name":"Locked"}).json()["id"]
    assert client.patch(base+"/features/"+features[1],json={"layer_id":layer}).status_code==200
    assert client.patch(base+"/layers/"+layer,json={"locked":True}).status_code==200
    failed=client.post(base+"/topology/move",json={
        "old":[.01,0],"new":[.0105,-.0001],
        "expected_revisions":{features[0]:0,features[1]:1},
    })
    assert failed.status_code==409
    first=client.get(base+"/features").json()["results"][0]
    assert first["geometry"]["coordinates"][0][1]==[.01,0]
