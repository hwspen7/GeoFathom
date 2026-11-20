"""Existing vector network tracing and shortest path regression."""
import os
import pytest
from fastapi.testclient import TestClient
from core.main import app

client=TestClient(app)


def test_connected_trace_and_projection():
    network=[[[0,0],[.01,0]],[[.01,0],[.01,.01]]]
    r=client.post("/edit/trace",json={
        "start":[.002, .00001],"end":[.00999,.008],
        "paths":network,"tolerance_m":20,
    })
    assert r.status_code==200,r.text
    item=r.json()
    assert item["geometry"]["type"]=="LineString"
    assert item["measurement"]["length_m"]>1500
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE")=="1":
        assert item["engine"]=="cpp-bvh"


def test_disconnected_trace_rejected():
    r=client.post("/edit/trace",json={
        "start":[0,0],"end":[.1,.1],
        "paths":[[[0,0],[.01,0]],[[.1,.1],[.1,.11]]],
    })
    assert r.status_code==422
    assert "disconnected" in r.json()["detail"].lower()


def test_trace_bounded_distance():
    assert client.post("/edit/trace",json={
        "start":[1,1],"end":[0,0],"paths":[[[0,0],[.01,0]]],
    }).status_code==422
