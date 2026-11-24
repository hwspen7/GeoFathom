"""Filter and atomically edit GIS attribute records."""
import pytest
from fastapi.testclient import TestClient
from core.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"attr.sqlite"))


def setup():
    project=client.post("/projects",json={"name":"Attributes"}).json()
    base="/projects/"+project["id"]
    features=[]
    for n,a in enumerate([100,200]):
        payload={"name":f"Building {n}","geometry":{
            "type":"Point","coordinates":[float(n),0.]},
            "source":"Manual","properties":{"height":a,"category":"building"}}
        response=client.post(base+"/features",json=payload)
        assert response.status_code==201,response.text
        features.append(response.json())
    return base,features


def test_attribute_query_filters_and_pagination():
    base,features=setup()
    search=client.post(base+"/attributes/query",json={
        "field":"height","operator":"gte","value":150})
    assert search.status_code==200,search.text
    assert search.json()["total"]==1
    assert search.json()["results"][0]["id"]==features[1]["id"]
    query=client.post(base+"/attributes/query",json={
        "field":"name","operator":"contains","value":"Building","limit":1})
    assert query.json()["total"]==2
    assert len(query.json()["results"])==1


def test_bulk_edit_atomic_conflicts_and_versions():
    base,features=setup()
    updates=[{"id":f["id"],"expected_revision":0,
              "properties":{"category":"warehouse","rank":i}} for i,f in enumerate(features)]
    r=client.patch(base+"/attributes/batch",json={"updates":updates})
    assert r.status_code==200,r.text
    assert r.json()["count"]==2
    history=client.get(base+"/features/"+features[0]["id"]+"/history").json()
    assert history["current_revision"]==1
    failed=client.patch(base+"/attributes/batch",json={"updates":updates})
    assert failed.status_code==409
    after=client.post(base+"/attributes/query",json={"field":"category","operator":"equals","value":"warehouse"})
    assert after.json()["total"]==2


def test_locked_attribute_changes_roll_back_all():
    base,features=setup()
    layer=client.post(base+"/layers",json={"name":"Locked"}).json()["id"]
    assert client.patch(base+"/features/"+features[1]["id"],json={"layer_id":layer}).status_code==200
    assert client.patch(base+"/layers/"+layer,json={"locked":True}).status_code==200
    r=client.patch(base+"/attributes/batch",json={"updates":[
        {"id":features[0]["id"],"expected_revision":0,"properties":{"edited":True}},
        {"id":features[1]["id"],"expected_revision":1,"properties":{"edited":True}},
    ]})
    assert r.status_code==409
    data=client.get(base+"/features").json()["results"]
    assert not any("edited" in f["properties"] for f in data)
