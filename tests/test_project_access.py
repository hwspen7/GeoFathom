from fastapi.testclient import TestClient
from core.main import app
from core.access import create_user,grant,revoke,permits
from storage.database import create_project,_connect

def test_project_membership_and_revocation(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"auth.sqlite"))
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","required")
    monkeypatch.setenv("GEOFATHOM_API_TOKEN","operator-"+"x"*40)
    first=create_project("Visible")["id"]
    second=create_project("Hidden")["id"]
    uid,token=create_user("Reader")
    grant(uid,first,"viewer")
    client=TestClient(app)
    headers={"X-GeoFathom-API-Key":token}
    def get(path):return client.get(path,headers=headers)
    def post(path,payload):return client.post(path,json=payload,headers=headers)
    root="/projects/"+first
    assert get("/projects").json()["total"]==1
    assert get("/projects").json()["results"][0]["id"]==first
    assert get(root).status_code==200
    assert get("/projects/"+second).status_code==403
    assert get("/imagery").status_code==403
    body={"name":"Point","geometry":{"type":"Point","coordinates":[10,20]}}
    assert post(root+"/features",body).status_code==403
    grant(uid,first,"editor")
    assert post(root+"/features",body).status_code==201
    assert client.delete(root,headers=headers).status_code==403
    assert post(root+"/jobs",{"kind":"rebuild_index"}).status_code==403
    assert post(root+"/jobs",{"kind":"spectral_index"}).status_code==403
    assert post(root+"/jobs",{"kind":"stac_ndvi"}).status_code==403
    assert get("/projects/"+second+"/features").status_code==403
    with _connect() as conn:
        stored=conn.execute("SELECT token_hash FROM access_users WHERE id=?",(uid,)).fetchone()[0]
        assert len(stored)==64 and stored!=token
    revoke(uid,first)
    assert get("/projects").json()["total"]==0
    assert get(root).status_code==403
    revoke(uid)
    assert get(root).status_code==401

def test_unknown_routes_deny_by_default():
    user={"id":"u","roles":{"p":"editor"}}
    for method,path in [("GET","/projects/p/unknown"),("POST","/projects/p/postgis"),
                        ("GET","/projects/q"),("DELETE","/projects/p"),("GET","/docs")]:
        assert not permits(user,method,path)
