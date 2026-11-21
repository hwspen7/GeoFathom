"""P0 selection, SQLite R-tree synchronization and topology QA regression tests."""
import concurrent.futures

import pytest
from fastapi.testclient import TestClient
from core.main import app

c=TestClient(app)

@pytest.fixture(autouse=True)
def db(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"features.sqlite"))

def polygon(x,y=.0):
    return {"type":"Polygon","coordinates":[[
        [x,y],[x+1,y],[x+1,y+1],[x,y+1],[x,y],
    ]]}

def point(x,y=.5):
    return {"type":"Point","coordinates":[x,y]}

def setup():
    p=c.post("/projects",json={"name":"Topology QA"}).json()
    root="/projects/"+p["id"]
    layer=c.get(root+"/workspace").json()["layers"][0]["id"]
    return root,layer

def add(root,name,geometry,layer=None):
    response=c.post(root+"/features",json={
        "name":name,"geometry":geometry,"layer_id":layer,
    })
    assert response.status_code==201,response.text
    return response.json()

def select(root,geometry,relation="intersects",**changes):
    return c.post(root+"/spatial/select",json={
        "geometry":geometry,"relation":relation,**changes,
    })

def test_exact_spatial_predicates_and_layer_visibility():
    root,layer=setup()
    inside=add(root,"Inside",point(.5))
    outside=add(root,"Outside",point(3))
    selector=polygon(0)
    selected=select(root,selector)
    assert selected.status_code==200,selected.text
    assert selected.json()["ids"]==[inside["id"]]
    assert select(root,selector,"within").json()["total"]==1
    assert select(root,selector,"contains").json()["total"]==0
    c.patch(root+"/layers/"+layer,json={"visible":False})
    assert select(root,selector).json()["total"]==0
    assert select(root,selector,visible_only=False).json()["total"]==1
    assert outside["id"] not in selected.json()["ids"]

def test_rtree_index_tracks_geometry_revision_and_deletion():
    root,layer=setup()
    item=add(root,"Move me",point(1))
    old=c.get(root+"/features/viewport",params={
        "west":.9,"south":.3,"east":1.1,"north":.7,
    })
    assert old.status_code==200,old.text
    assert old.json()["total"]==1
    moved=c.patch(root+"/features/"+item["id"],json={
        "geometry":point(5),"expected_revision":0,
    })
    assert moved.status_code==200,moved.text
    assert c.get(root+"/features/viewport",params={
        "west":.9,"south":.3,"east":1.1,"north":.7,
    }).json()["total"]==0
    assert c.get(root+"/features/viewport",params={
        "west":4.9,"south":.3,"east":5.1,"north":.7,
    }).json()["total"]==1
    assert c.delete(root+"/features/"+item["id"]).status_code==204
    assert c.get(root+"/features/viewport",params={
        "west":4.9,"south":.3,"east":5.1,"north":.7,
    }).json()["total"]==0

def test_viewport_pagination_and_invalid_coordinates():
    root,_=setup()
    for i in range(14):add(root,str(i),point(i/100))
    opts={"west":-.1,"south":0,"east":.3,"north":1}
    page=c.get(root+"/features/viewport",params={**opts,"limit":5,"offset":5})
    assert page.status_code==200,page.text
    assert page.json()["total"]==14
    assert len(page.json()["results"])==5
    assert page.json()["indexed"] is True
    assert all(item["measurement"]["geometry_type"]=="Point"
               for item in page.json()["results"])
    for bbox in [(2,0,1,1),(0,-92,1,1),(-190,0,2,1)]:
        bad=c.get(root+"/features/viewport",params=dict(zip(("west","south","east","north"),bbox)))
        assert bad.status_code==422

def test_spatial_selection_filters_by_layer_and_exact_interior():
    root,layer=setup()
    second=c.post(root+"/layers",json={"name":"Second"}).json()["id"]
    a=add(root,"A",point(.2),layer)
    b=add(root,"B",point(.4),second)
    response=select(root,polygon(0),layer_ids=[second])
    assert response.status_code==200
    assert response.json()["ids"]==[b["id"]]
    forbidden=select(root,polygon(0),layer_ids=["another-project-id"])
    assert forbidden.status_code==404

def test_quality_detects_overlap_duplicate_and_gap_in_declared_aoi():
    root,_=setup()
    add(root,"First",polygon(0,0))
    add(root,"Second",polygon(.5,0))
    add(root,"Same as first",polygon(0,0))
    aoi={"type":"Polygon","coordinates":[[
        [0,0],[2.5,0],[2.5,1],[0,1],[0,0],
    ]]}
    report=c.post(root+"/quality/topology",json={
        "study_area":aoi,"minimum_area_m2":10,
    })
    assert report.status_code==200,report.text
    output=report.json()
    assert output["counts"]["duplicate"]>=1
    assert output["counts"]["overlap"]>=1
    assert output["counts"]["gap"]>=1
    assert any(item["geometry"]["type"] in ("Polygon","MultiPolygon") for item in output["issues"])

def test_quality_dangles_and_empty_result():
    root,_=setup()
    assert c.post(root+"/quality/topology",json={}).json()["issue_count"]==0
    add(root,"Open line",{"type":"LineString","coordinates":[[0,0],[1,0]]})
    report=c.post(root+"/quality/topology",json={"check_dangles":True})
    assert report.status_code==200
    assert report.json()["counts"]["dangle"]==2
    without=c.post(root+"/quality/topology",json={"check_dangles":False})
    assert without.json()["issue_count"]==0

def test_invalid_spatial_inputs_are_rejected():
    root,_=setup()
    for req in [
        {"geometry":point(190)},
        {"geometry":polygon(0),"relation":"invalid"},
        {"geometry":polygon(0),"limit":10000},
    ]:
        assert c.post(root+"/spatial/select",json=req).status_code==422

def test_legacy_features_backfill_rtree():
    import sqlite3
    from storage.database import database_path
    root,_=setup()
    add(root,"Known",point(1))
    with sqlite3.connect(database_path()) as connection:
        connection.execute("DELETE FROM feature_bounds")
        connection.commit()
    resp=c.get(root+"/features/viewport",params={
        "west":0,"south":0,"east":2,"north":1,
    })
    assert resp.status_code==200,resp.text
    assert resp.json()["total"]==1

def test_quality_detects_empty_aoi_coverage():
    # A fully uncovered study area must be reported even when the project
    # contains no polygon features (or only line features).
    root,_=setup()
    aoi=polygon(0,0)
    payload={"study_area":aoi,"minimum_area_m2":10,"check_dangles":False}
    for with_line in (False,True):
        if with_line:
            add(root,"Centerline",{"type":"LineString","coordinates":[[0.2,0.2],[0.8,0.2]]})
        response=c.post(root+"/quality/topology",json=payload)
        assert response.status_code==200,response.text
        report=response.json()
        assert report["counts"]=={"gap":1}
        assert report["issue_count"]==1
        assert report["issues"][0]["geometry"]==aoi
        assert report["issues"][0]["area_m2"]>0
        assert report["checked_features"]==int(with_line)
    # Without a defined study area, missing exterior coverage is unknowable.
    assert c.post(root+"/quality/topology",json={"check_dangles":False}).json()["issue_count"]==0
