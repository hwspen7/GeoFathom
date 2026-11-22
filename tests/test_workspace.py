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



def test_split_batch_is_atomic_on_invalid_geometry():
    root,fid=setup()
    suffix=root.removeprefix("/projects/")
    valid={"name":"Valid","geometry":polygon(),"source":"Test"}
    bad={"name":"Invalid","geometry":{"type":"Polygon","coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]},"source":"Test"}
    failed=client.post(root+"/features/batch",json={"features":[valid,bad]})
    assert failed.status_code==422
    assert client.get(root+"/workspace").json()["total"]==1
    saved=client.post(root+"/features/batch",json={"features":[valid,valid]})
    assert saved.status_code==201,saved.text
    assert saved.json()["created"]==2
    assert client.get(root+"/workspace").json()["total"]==3


def test_layer_lock_prevents_deletion_without_time_of_check_gap():
    root,fid=setup()
    lid=client.get(root+"/layers").json()[0]["id"]
    assert client.patch(root+"/layers/"+lid,json={"locked":True}).status_code==200
    assert client.delete(root+"/features/"+fid).status_code==422
    assert client.get(root+"/workspace").json()["total"]==1
    assert client.patch(root+"/layers/"+lid,json={"locked":False}).status_code==200
    assert client.delete(root+"/features/"+fid).status_code==204
    assert client.get(root+"/workspace").json()["total"]==0


def test_existing_feature_layer_is_stable_after_layer_reordering():
    root,fid=setup()
    original=client.get(root+"/workspace").json()["features"][0]["layer_id"]
    new=client.post(root+"/layers",json={"name":"Above","color":"#ff8800"}).json()
    assert client.patch(root+"/layers/"+new["id"],json={"z_index":-100}).status_code==200
    updated=client.get(root+"/workspace").json()["features"][0]
    assert updated["layer_id"]==original


def test_concurrent_revision_writers_have_exactly_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    root,fid=setup()
    barrier=Barrier(2)
    def update(name):
        barrier.wait(timeout=5)
        return client.patch(root+"/features/"+fid,json={"name":name,"expected_revision":0})
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(update,["first","second"]))
    assert sorted(x.status_code for x in outcomes)==[200,409]
    winner=next(x.json() for x in outcomes if x.status_code==200)
    saved=client.get(root+"/workspace").json()["features"][0]
    assert saved["name"]==winner["name"] and saved["revision"]==1
    history=client.get(root+"/features/"+fid+"/history").json()
    assert [item["revision"] for item in history["versions"]]==[1,0]
    assert history["versions"][0]["name"]==winner["name"]


def test_project_scoped_feature_ids_cannot_read_or_mutate_another_project():
    root,fid=setup()
    other,other_id=setup()
    feature=client.get(root+"/workspace").json()["features"][0]
    wrong_layer=client.get(other+"/workspace").json()["layers"][0]["id"]
    assert client.patch(root+"/features/"+fid,json={"layer_id":wrong_layer,"expected_revision":0}).status_code==404
    path=other+"/features/"+fid
    assert client.patch(path,json={"name":"corrupt","expected_revision":0}).status_code==404
    assert client.get(path+"/history").status_code==404
    assert client.post(path+"/copy").status_code==404
    assert client.post(path+"/restore/0").status_code==404
    assert client.delete(path).status_code==404
    assert client.get(root+"/workspace").json()["features"][0]==feature
    assert client.get(other+"/workspace").json()["features"][0]["id"]==other_id


def test_workspace_reads_keep_geometry_and_revision_in_one_snapshot():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from storage.workspace import workspace,update_feature
    root,fid=setup()
    project=root.removeprefix("/projects/")
    barrier=Barrier(2)
    def write():
        barrier.wait(timeout=5)
        for revision in range(1,21):
            update_feature(project,fid,geometry=polygon(revision*.001),
                name=f"r{revision}",expected_revision=revision-1)
    def read():
        barrier.wait(timeout=5)
        for _ in range(40):
            state=workspace(project)
            assert state["total"]==1 and len(state["features"])==1
            feature=state["features"][0]
            revision=feature["revision"]
            assert feature["geometry"]["coordinates"][0][0][0]==pytest.approx(revision*.001)
            assert feature["name"]==("Plot" if revision==0 else f"r{revision}")
            assert feature["layer_id"] in {layer["id"] for layer in state["layers"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer=executor.submit(write);reader=executor.submit(read)
        writer.result(timeout=30);reader.result(timeout=30)
    assert workspace(project)["features"][0]["revision"]==20


def test_parallel_first_workspace_load_has_one_default_layer():
    from concurrent.futures import ThreadPoolExecutor
    from storage.workspace import workspace
    project=client.post("/projects",json={"name":"Concurrent default"}).json()["id"]
    with ThreadPoolExecutor(max_workers=4) as workers:
        snapshots=list(workers.map(workspace,[project]*8))
    assert all(len(item["layers"])==1 and item["total"]==0 for item in snapshots)
    assert len({item["layers"][0]["id"] for item in snapshots})==1


def test_trash_is_project_scoped_and_restores_identity_and_revisions():
    root,fid=setup()
    changed=client.patch(root+"/features/"+fid,json={"name":"Updated parcel","expected_revision":0})
    assert changed.status_code==200
    assert client.delete(root+"/features/"+fid+"?expected_revision=0").status_code==409
    assert client.delete(root+"/features/"+fid+"?expected_revision=1").status_code==204
    assert client.get(root+"/workspace").json()["total"]==0
    trash=client.get(root+"/trash").json()
    assert trash["total"]==1 and trash["items"][0]["feature_id"]==fid
    other=client.post("/projects",json={"name":"Other"}).json()["id"]
    assert client.get("/projects/"+other+"/trash").json()["total"]==0
    assert client.post("/projects/"+other+"/trash/"+fid+"/restore").status_code==404
    layer=trash["items"][0]["layer_id"]
    assert client.patch(root+"/layers/"+layer,json={"locked":True}).status_code==200
    assert client.post(root+"/trash/"+fid+"/restore").status_code==409
    assert client.patch(root+"/layers/"+layer,json={"locked":False}).status_code==200
    restored=client.post(root+"/trash/"+fid+"/restore")
    assert restored.status_code==200,restored.text
    assert restored.json()["id"]==fid and restored.json()["revision"]==2
    assert restored.json()["name"]=="Updated parcel"
    assert client.get(root+"/trash").json()["total"]==0
    assert [v["revision"] for v in client.get(root+"/features/"+fid+"/history").json()["versions"]]==[2,1,0]

def test_large_atomic_feature_batch_over_100_is_not_silently_truncated():
    root,_=setup()
    data={"features":[{"name":str(i),"geometry":{"type":"Point","coordinates":[i/1000,1]}} for i in range(130)]}
    result=client.post(root+"/features/batch",json=data)
    assert result.status_code==201,result.text
    assert result.json()["created"]==130
    assert client.get(root+"/workspace").json()["total"]==131
