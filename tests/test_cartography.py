"""Cartographic labels, note annotations, style validation, isolation and persistence."""
import json
import math
import os

import pytest
from fastapi.testclient import TestClient

from core.main import app
from storage.cartography import default_style

client=TestClient(app)


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"cartography.sqlite"))


def project():
    created=client.post("/projects",json={"name":"Cartography project"})
    assert created.status_code==201
    return "/projects/"+created.json()["id"]


def first_layer(root):
    response=client.get(root+"/workspace")
    assert response.status_code==200,response.text
    return response.json()["layers"][0]


def patch(root,layer,payload):
    return client.patch(root+"/layers/"+layer["id"]+"/style",json=payload)


def test_default_styles_are_complete_and_independent():
    a=default_style();b=default_style()
    a["labels"]["field"]="height"
    assert b["labels"]["field"]=="name"
    root=project();layer=first_layer(root)
    assert layer["style_revision"]==0
    assert layer["style"]["labels"]["enabled"] is False
    assert layer["style"]["symbol"]["fill_opacity"]==pytest.approx(.17)


def test_all_supported_label_style_options_persist_after_reloading_database():
    root=project();layer=first_layer(root)
    options={"labels":{
        "enabled":True,"field":"height","font_size":17,
        "text_color":"#aabbcc","halo_color":"#010101","halo_width":2,
        "min_zoom":8,"max_zoom":19,"allow_overlap":True,
    },"symbol":{"fill_opacity":.65,"line_width":4,
                "point_radius":7,"stroke_color":"#112233"}}
    response=patch(root,layer,{**options,"expected_revision":0})
    assert response.status_code==200,response.text
    assert response.json()["style_revision"]==1
    reloaded=first_layer(root)
    for section in options:
        for name,value in options[section].items():
            assert reloaded["style"][section][name]==value
    assert reloaded["style_revision"]==1


def test_layer_style_update_is_atomic_on_invalid_setting():
    root=project();layer=first_layer(root)
    bad=patch(root,layer,{
        "labels":{"enabled":True,"font_size":8},"symbol":{"fill_opacity":.55}})
    assert bad.status_code==422
    current=first_layer(root)
    assert current["style_revision"]==0
    assert current["style"]["labels"]["enabled"] is False
    assert current["style"]["symbol"]["fill_opacity"]==pytest.approx(.17)


@pytest.mark.parametrize("patch_body",[
    {"labels":{"font_size":8}},
    {"labels":{"font_size":29}},
    {"labels":{"font_size":True}},
    {"labels":{"field":""}},
    {"labels":{"field":"x"*65}},
    {"labels":{"text_color":"<script>alert(1)</script>"}},
    {"labels":{"halo_width":4,"font_size":12}},
    {"labels":{"min_zoom":20,"max_zoom":8}},
    {"labels":{"enabled":"true"}},
    {"labels":{"allow_overlap":1}},
    {"symbol":{"fill_opacity":2}},
    {"symbol":{"line_width":0}},
    {"symbol":{"point_radius":21}},
    {"symbol":{"stroke_color":"#abc"}},
    {"unknown":{"enabled":True}},
    {"labels":{"bogus":True}},
])
def test_bad_label_payloads_are_rejected(patch_body):
    root=project();layer=first_layer(root)
    r=patch(root,layer,patch_body)
    assert r.status_code==422,r.text
    assert first_layer(root)["style_revision"]==0


def test_revision_conflict_prevents_silent_overwrite():
    root=project();layer=first_layer(root)
    assert patch(root,layer,{"labels":{"enabled":True},"expected_revision":0}).status_code==200
    stale=patch(root,layer,{"labels":{"field":"category"},"expected_revision":0})
    assert stale.status_code==409
    assert first_layer(root)["style"]["labels"]["field"]=="name"


def test_project_scoping_and_nonexistent_layer():
    root=project();other=project()
    first=first_layer(root);second=first_layer(other)
    assert patch(other,first,{"labels":{"enabled":True}}).status_code==404
    assert patch(root,second,{"labels":{"enabled":True}}).status_code==404
    assert patch(root,first,{"labels":{"enabled":True}}).status_code==200


def test_independent_layer_styles_and_visibility():
    root=project();first=first_layer(root)
    second=client.post(root+"/layers",json={"name":"Road labels","color":"#f00d32"}).json()
    assert patch(root,second,{"labels":{"enabled":True,"field":"road_name"}}).status_code==200
    assert client.patch(root+"/layers/"+second["id"],json={"visible":False}).status_code==200
    new_layers=client.get(root+"/workspace").json()["layers"]
    assert new_layers[0]["style"]["labels"]["enabled"] is False
    assert next(x for x in new_layers if x["id"]==second["id"])["style"]["labels"]["enabled"] is True
    assert next(x for x in new_layers if x["id"]==second["id"])["visible"]==0


def test_creating_annotation_saves_point_and_export_roundtrip():
    root=project()
    layer=first_layer(root)
    assert patch(root,layer,{"labels":{"enabled":True}}).status_code==200
    response=client.post(root+"/annotations",json={
        "text":"Survey monument — 北角","position":[-83.05,40.04],
        "layer_id":layer["id"],
    })
    assert response.status_code==201,response.text
    assert response.json()["geometry"]["type"]=="Point"
    assert response.json()["properties"]["annotation_text"]=="Survey monument — 北角"
    assert response.json()["properties"]["annotation"] is True
    exported=client.get(root+"/export").json()
    assert exported["features"][0]["properties"]["annotation_text"]=="Survey monument — 北角"
    assert exported["features"][0]["geometry"]["coordinates"]==[-83.05,40.04]


def test_annotation_requires_valid_coordinates_and_printable_text():
    root=project()
    for body in [
        {"text":"","position":[-83,40]},
        {"text":"X"*121,"position":[-83,40]},
        {"text":"Valid","position":[-181,40]},
        {"text":"Valid","position":[-83,91]},
        {"text":chr(7),"position":[-83,40]},
        {"text":"Valid","position":[-83]},
    ]:
        r=client.post(root+"/annotations",json=body)
        assert r.status_code==422,(body,r.text)
    assert client.get(root+"/workspace").json()["total"]==0


def test_annotation_respects_layer_lock_and_isolation():
    root=project();layer=first_layer(root)
    assert client.patch(root+"/layers/"+layer["id"],json={"locked":True}).status_code==200
    r=client.post(root+"/annotations",json={"text":"Blocked","position":[0,0],"layer_id":layer["id"]})
    assert r.status_code==409,r.text
    assert client.get(root+"/workspace").json()["total"]==0


def test_style_survives_feature_revision_and_is_independent_of_geometry_history():
    root=project();layer=first_layer(root)
    assert patch(root,layer,{"labels":{"enabled":True}}).status_code==200
    feat=client.post(root+"/features",json={
        "name":"Area","geometry":{"type":"Point","coordinates":[0,0]},
    }).json()
    assert client.patch(root+"/features/"+feat["id"],json={"name":"Area 2","expected_revision":0}).status_code==200
    assert first_layer(root)["style_revision"]==1
    assert first_layer(root)["style"]["labels"]["enabled"] is True



def test_categorized_colors_save_and_survive_project_reload():
    root=project()
    layer=first_layer(root)
    colors={"residential":"#aabbcc","industrial":"#112233"}
    changed=patch(root,layer,{
        "symbol":{"category_field":"landuse","category_colors":colors},
        "expected_revision":0,
    })
    assert changed.status_code==200,changed.text
    persisted=first_layer(root)["style"]["symbol"]
    assert persisted["category_field"]=="landuse"
    assert persisted["category_colors"]==colors
    assert first_layer(root)["style_revision"]==1


@pytest.mark.parametrize("colors",[
    {"industrial":"not-a-color"},
    {"x"*81:"#112233"},
    {"illegal\nkey":"#112233"},
    {str(i):"#112233" for i in range(21)},
    ["#112233"],
    {"industrial":123},
])
def test_invalid_category_palettes_are_rejected_atomically(colors):
    root=project();layer=first_layer(root)
    bad=patch(root,layer,{"symbol":{
        "category_field":"landuse","category_colors":colors}})
    assert bad.status_code==422,bad.text
    assert first_layer(root)["style_revision"]==0


def test_clear_categorization_keeps_label_settings():
    root=project();layer=first_layer(root)
    update=patch(root,layer,{
        "labels":{"enabled":True,"field":"name"},
        "symbol":{"category_field":"zone","category_colors":{"1":"#aabbcc"}},
    })
    assert update.status_code==200
    clear=patch(root,layer,{
        "symbol":{"category_field":"","category_colors":{}},
        "expected_revision":1,
    })
    assert clear.status_code==200
    style=first_layer(root)["style"]
    assert style["labels"]["enabled"] is True
    assert style["symbol"]["category_colors"]=={}
