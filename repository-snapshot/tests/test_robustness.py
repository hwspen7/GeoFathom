"""Deterministic geometry fuzzing, project scale bounds and conflict smoke tests.

Seeded random scenarios catch edge cases without introducing flaky test order.
All geographic comparisons use WGS84 and avoid the antimeridian/polar regions.
"""
import math
import random
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pyproj import Geod

from core.main import app
from geometry.measure import GeometryError,measure_geometry
from geometry.topology import contains_point
from storage.database import StorageError
from storage.workspace import update_feature

client=TestClient(app)
geod=Geod(ellps="WGS84")


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"robustness.sqlite"))


def rectangle(lon,lat,width,height):
    return {"type":"Polygon","coordinates":[[
        [lon,lat],[lon+width,lat],[lon+width,lat+height],
        [lon,lat+height],[lon,lat],
    ]]}


def test_seeded_random_geodesic_area_and_perimeter():
    randomizer=random.Random(1648)
    for _ in range(240):
        longitude=randomizer.uniform(-145,145)
        latitude=randomizer.uniform(-65,65)
        width=randomizer.uniform(.001,.04)
        height=randomizer.uniform(.001,.04)
        geometry=rectangle(longitude,latitude,width,height)
        measured=measure_geometry(geometry)
        expected,_=geod.polygon_area_perimeter(
            [longitude,longitude+width,longitude+width,longitude,longitude],
            [latitude,latitude,latitude+height,latitude+height,latitude],
        )
        assert measured["area_m2"]==pytest.approx(abs(expected),rel=1e-8)
        assert measured["perimeter_m"]>0
        assert measured["coordinate_count"]==5
        assert contains_point(geometry,longitude+width/2,latitude+height/2)
        assert not contains_point(geometry,longitude+width*2,latitude+height*2)


@pytest.mark.parametrize("geometry",[
    {"type":"Polygon","coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]},
    {"type":"Polygon","coordinates":[[[0,0],[1,0],[2,0],[0,0]]]},
    {"type":"LineString","coordinates":[[0,0]]},
    {"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]],[[2,2],[3,2],[3,3],[2,2]]]},
    {"type":"Point","coordinates":[181,0]},
    {"type":"Point","coordinates":[0,-91]},
    {"type":"Point","coordinates":[True,0]},
    {"type":"Polygon","coordinates":[]},
    {"type":"Polygon","coordinates":[[]]},
    {"type":"Polygon","coordinates":[[0,1]]},
    {"type":"GeometryCollection","geometries":[]},
])
def test_malformed_geometry_rejected_without_unhandled_server_error(geometry):
    with pytest.raises(GeometryError):
        measure_geometry(geometry)
    response=client.post("/measure",json={"geometry":geometry})
    assert response.status_code==422,response.text


def test_two_hundred_features_keep_label_layer_and_workspace_stable():
    project=client.post("/projects",json={"name":"Stress project"}).json()
    root="/projects/"+project["id"]
    layer=client.get(root+"/workspace").json()["layers"][0]
    assert client.patch(root+"/layers/"+layer["id"]+"/style",json={
        "labels":{"enabled":True,"field":"category"},
        "symbol":{"category_field":"category",
                  "category_colors":{"A":"#112233","B":"#334455"}},
    }).status_code==200
    for batch in range(2):
        features=[{
            "name":f"Asset {batch*100+i}",
            "geometry":{"type":"Point",
                        "coordinates":[-83+(i%20)*.001,40+(i//20)*.001]},
            "properties":{"category":"A" if i%2 else "B","weight":i},
            "source":"Synthetic test",
        } for i in range(100)]
        r=client.post(root+"/features/batch",json={"features":features,
                                                   "layer_id":layer["id"]})
        assert r.status_code==201,r.text
    state=client.get(root+"/workspace").json()
    assert state["total"]==200
    assert len(state["features"])==200
    assert state["layers"][0]["style"]["labels"]["enabled"]
    assert state["layers"][0]["style"]["symbol"]["category_colors"]["B"]=="#334455"
    assert len({item["id"] for item in state["features"]})==200


def test_optimistic_revision_concurrent_edits_accept_only_one_writer():
    project=client.post("/projects",json={"name":"Concurrency"}).json()
    root="/projects/"+project["id"]
    created=client.post(root+"/features",json={
        "name":"Shared","geometry":{"type":"Point","coordinates":[0,20]},
    }).json()
    fid=created["id"]
    def update(index):
        try:
            return update_feature(project["id"],fid,
                                  name="Updated "+str(index),expected_revision=0)["revision"]
        except StorageError:
            return None
    with ThreadPoolExecutor(max_workers=3) as executor:
        outputs=list(executor.map(update,range(3)))
    assert outputs.count(1)==1
    assert outputs.count(None)==2
    current=client.get(root+"/workspace").json()["features"][0]
    assert current["revision"]==1
