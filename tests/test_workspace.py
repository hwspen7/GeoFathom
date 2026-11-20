"""Layer visibility/locking, copy, history, revert and conflict testing."""

import pytest
from fastapi.testclient import TestClient
from core.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def db(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"workspace.sqlite"))


def polygon(x=0):
    return {"type":"Polygon","coordinates":[[
        [x,0],[x+.01,0],[x+.01,.01],[x,.01],[x,0],
    ]]}


def setup():
    project=client.post("/projects",json={"name":"Editor history"}).json()
    path=f"/projects/{project['id']}"
    item=client.post(path+"/features",json={
        "name":"Plot","geometry":polygon(),"source":"User drawn",
    })
    assert item.status_code==201,item.text
    return path,item.json()["id"]


def test_layer_visibility_lock_and_reorder():
    root,fid=setup()
    initial=client.get(root+"/workspace").json()
    assert len(initial["layers"])==1 and len(initial["features"])==1
    new=client.post(root+"/layers",json={"name":"Buildings","color":"#ff8800"})
    assert new.status_code==201,new.text
    lid=new.json()["id"]
    update=client.patch(root+"/layers/"+lid,json={
        "visible":False,"locked":True,"z_index":-1,
    })
    assert update.status_code==200 and update.json()["visible"]==0
    assert update.json()["locked"]==1
    assert client.patch(root+"/features/"+fid,json={"layer_id":lid}).status_code==409
    assert client.patch(root+"/layers/"+lid,json={"locked":False}).status_code==200
    moved=client.patch(root+"/features/"+fid,json={"layer_id":lid,"expected_revision":0})
    assert moved.status_code==200,moved.text
    assert moved.json()["layer_id"]==lid
    assert client.patch(root+"/layers/"+lid,json={"locked":True}).status_code==200
    assert client.patch(root+"/features/"+fid,json={"name":"blocked"}).status_code==409
    assert client.delete(root+"/layers/"+lid).status_code==422
    assert client.get(root+"/workspace").json()["features"][0]["layer_id"]==lid
    assert client.patch(root+"/layers/"+lid,json={"locked":False}).status_code==200


def test_immutable_versions_restore_and_conflict():
    root,fid=setup()
    newer=client.patch(root+"/features/"+fid,json={
        "geometry":polygon(.002),"name":"Adjusted","expected_revision":0,
    })
    assert newer.status_code==200,newer.text
    assert newer.json()["revision"]==1
    conflict=client.patch(root+"/features/"+fid,json={
        "name":"stale","expected_revision":0,
    })
    assert conflict.status_code==409
    nextedit=client.patch(root+"/features/"+fid,json={
        "name":"Another","expected_revision":1,
    })
    assert nextedit.status_code==200
    history=client.get(root+"/features/"+fid+"/history").json()
    assert [v["revision"] for v in history["versions"]]==[2,1,0]
    restored=client.post(root+"/features/"+fid+"/restore/0")
    assert restored.status_code==200,restored.text
    assert restored.json()["revision"]==3
    assert restored.json()["name"]=="Plot"
    assert restored.json()["geometry"]["coordinates"][0][0][0]==0


def test_copy_and_saved_workspace():
    root,fid=setup()
    copied=client.post(root+"/features/"+fid+"/copy")
    assert copied.status_code==201,copied.text
    assert copied.json()["name"].endswith(" copy")
    workspace=client.get(root+"/workspace").json()
    assert workspace["total"]==2
    assert len({x["id"] for x in workspace["features"]})==2
    assert client.get(root+"/features/"+fid+"/history").json()["current_revision"]==0


def test_bad_layer_and_geometry_rejected():
    root,fid=setup()
    assert client.post(root+"/layers",json={"name":"Bad","color":"red"}).status_code==422
    assert client.patch(root+"/features/"+fid,json={
        "geometry":{"type":"Polygon","coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]},
    }).status_code==422
    assert client.get(root+"/workspace").json()["features"][0]["revision"]==0
    assert client.patch(root+"/features/"+fid,json={"layer_id":"missing"}).status_code==404
