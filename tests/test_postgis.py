"""PostGIS provider-off behavior, authorization and real optional service integration.

Supply GEOFATHOM_TEST_POSTGIS_DSN to run a live server + GiST spatial
index acceptance test. Without that env, local SQLite CI remains self-contained.
"""
import os

import pytest
from fastapi.testclient import TestClient
from core.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def setup(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"postgis.sqlite"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN","postgis-admin")
    if os.getenv("GEOFATHOM_TEST_POSTGIS_DSN"):
        monkeypatch.setenv("GEOFATHOM_POSTGIS_DSN",os.environ["GEOFATHOM_TEST_POSTGIS_DSN"])
    else:
        monkeypatch.delenv("GEOFATHOM_POSTGIS_DSN",raising=False)


def project():
    response=client.post("/projects",json={"name":"PostGIS mirror"})
    assert response.status_code==201,response.text
    return "/projects/"+response.json()["id"]


def add(root,name,xy):
    return client.post(root+"/features",json={"name":name,
        "geometry":{"type":"Point","coordinates":list(xy)},
        "properties":{"name":name,"height":18},
    })


def test_postgis_is_not_falsely_reported_connected_when_unconfigured(monkeypatch):
    monkeypatch.delenv("GEOFATHOM_POSTGIS_DSN",raising=False)
    state=client.get("/postgis/status")
    assert state.status_code==200
    assert state.json()["connected"] is False
    assert state.json()["configured"] is False


def test_postgis_admin_required_and_clear_error_if_offline(monkeypatch):
    monkeypatch.delenv("GEOFATHOM_POSTGIS_DSN",raising=False)
    root=project()
    denied=client.post(root+"/postgis/sync",json={})
    assert denied.status_code==403
    unavailable=client.post(root+"/postgis/sync",json={},
        headers={"X-GeoFathom-Admin-Token":"postgis-admin"})
    assert unavailable.status_code==503,unavailable.text


@pytest.mark.skipif(not os.getenv("GEOFATHOM_TEST_POSTGIS_DSN"),
                    reason="PostGIS service not provided for live integration.")
def test_live_postgis_sync_gist_spatial_filter_revision_and_purge():
    root=project()
    a=add(root,"inside",[-83,40])
    b=add(root,"outside",[-81,40])
    assert a.status_code==201 and b.status_code==201
    uid=root.split("/")[-1]
    from storage.postgis import _connect_pg
    with _connect_pg() as conn:
        before=conn.execute("SELECT postgis_version()").fetchone()[0]
        assert before
    sync=client.post(root+"/postgis/sync",json={"max_features":100},
        headers={"X-GeoFathom-Admin-Token":"postgis-admin"})
    assert sync.status_code==200,sync.text
    assert sync.json()["synchronized"]==2
    assert sync.json()["atomic"] is True
    query={"west":-84,"south":39.5,"east":-82,"north":40.5}
    page=client.get(root+"/postgis/features",params=query)
    assert page.status_code==200,page.text
    assert page.json()["total"]==1
    assert page.json()["results"][0]["name"]=="inside"
    assert page.json()["indexed"] is True
    assert page.json()["results"][0]["measurement"]["geometry_type"]=="Point"
    assert page.json()["results"][0]["created_at"]
    revised=client.patch(root+"/features/"+a.json()["id"],json={
        "geometry":{"type":"Point","coordinates":[-80,40]},
        "expected_revision":0,
    })
    assert revised.status_code==200,revised.text
    again=client.post(root+"/postgis/sync",json={"max_features":100},
        headers={"X-GeoFathom-Admin-Token":"postgis-admin"})
    assert again.status_code==200,again.text
    assert client.get(root+"/postgis/features",params=query).json()["total"]==0
    with _connect_pg() as conn:
        index=conn.execute("""SELECT indexname FROM pg_indexes
            WHERE tablename='geofathom_features' AND indexname='geofathom_features_geom_gix'
        """).fetchone()
        assert index is not None
    removed=client.delete(root+"/postgis",
        headers={"X-GeoFathom-Admin-Token":"postgis-admin"})
    assert removed.status_code==200,removed.text
    assert removed.json()["removed"]==2
