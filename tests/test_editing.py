"""GIS editor: C++ primitives, topology, construction and API errors."""

import os
import pytest
from fastapi.testclient import TestClient
from core.main import app
from geometry.editing import simplify, snap

client=TestClient(app)


def square(a=0,b=0,c=.02,d=.02):
    return {"type":"Polygon","coordinates":[[[a,b],[c,b],[c,d],[a,d],[a,b]]]}


def test_shapes_are_real_geodesic_geometries():
    rectangle=client.post("/edit/construct",json={
        "mode":"rectangle","vertices":[[0,0],[.01,.01]]})
    assert rectangle.status_code==200,rectangle.text
    assert rectangle.json()["measurement"]["area_m2"]>1_000_000
    circle=client.post("/edit/construct",json={
        "mode":"circle","vertices":[[0,0]],"radius_m":1000,"segments":72})
    assert circle.status_code==200,circle.text
    assert 3_000_000 < circle.json()["measurement"]["area_m2"] < 3_200_000
    bearing=client.post("/edit/construct",json={
        "mode":"bearing","vertices":[[0,0]],"bearing_deg":90,"length_m":1000})
    assert bearing.status_code==200,bearing.text
    assert bearing.json()["measurement"]["length_m"]==pytest.approx(1000,abs=.01)


def test_holes_polygon_split_and_negative_cases():
    hollow=client.post("/edit/hole",json={
        "polygon":square(),"other":square(.005,.005,.015,.015)})
    assert hollow.status_code==200,hollow.text
    assert len(hollow.json()["geometry"]["coordinates"])==2
    cutting={"type":"LineString","coordinates":[[.01,-.01],[.01,.03]]}
    parts=client.post("/edit/split",json={"polygon":square(),"other":cutting})
    assert parts.status_code==200,parts.text
    assert len(parts.json()["features"])==2
    assert client.post("/edit/split",json={
        "polygon":square(),"other":{"type":"LineString","coordinates":[[1,1],[2,2]]}}).status_code==422
    assert client.post("/edit/hole",json={
        "polygon":square(),"other":square(.01,.01,.03,.03)}).status_code==422


def test_validate_and_geodesic_move():
    bowtie={"type":"Polygon","coordinates":[[[0,0],[1,1],[0,1],[1,0],[0,0]]]}
    assert client.post("/edit/validate",json={"geometry":bowtie}).json()["valid"] is False
    shifted=client.post("/edit/move",json={
        "geometry":square(),"bearing_deg":90,"distance_m":100})
    assert shifted.status_code==200,shifted.text
    assert shifted.json()["measurement"]["area_m2"] > 0
    assert client.post("/edit/construct",json={
        "mode":"rectangle","vertices":[[0,0],[0,0]]}).status_code==422


def test_cpp_snap_and_simplify_fallback():
    path=[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]
    nearest=snap([.000001,.000001],[path],10)
    assert nearest["snapped"] and nearest["kind"]=="vertex"
    assert nearest["coordinate"]==pytest.approx([0,0],abs=1e-6)
    edge=snap([.005,-.00001],[path],10)
    assert edge["snapped"] and edge["kind"]=="edge"
    simplified=simplify([[0,0],[.002,0],[.004,0],[.006,0]],1)
    assert simplified["retained"]==2
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE")=="1":
        assert nearest["engine"]=="cpp"
        assert simplified["engine"]=="cpp"
    assert client.post("/edit/snap",json={"coordinate":[0,0],"paths":[path],"tolerance_m":10}).status_code==200
    assert client.post("/edit/snap",json={"coordinate":[0,0],"paths":[],"tolerance_m":999}).status_code==422
