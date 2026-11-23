"""Cartographic PDF validation and geometry branch acceptance.

All PDFs are rendered by the actual reportlab pipeline and checked as
documents, including non-polygon map features and user-defined labels.
"""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.lib.colors import Color

from cartography import printing
from core.main import app

client=TestClient(app)

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"print-extra.sqlite"))


@pytest.mark.parametrize("value",["invalid","",None,"#fg00gg"])
def test_invalid_cartographic_color_falls_back_to_visible_default(value):
    assert isinstance(printing._rgb(value),Color)
    assert printing._rgb(value)==printing._rgb("#2563eb")


@pytest.mark.parametrize("value,expected",[
    (None,1),(0,1),(-100,1),(.03,1),(1,1),(3,2),(8,5),(20,20),(300,200),
])
def test_scale_bar_uses_clean_human_measurements(value,expected):
    assert printing._nice_distance(value)==expected


def test_integer_hex_color_is_valid_and_deterministic():
    # ReportLab accepts integer RGB hex values. Treating them as invalid
    # would incorrectly constrain a legitimate renderer input.
    assert printing._rgb(123)==printing._rgb(0x00007b)


def test_map_label_sanitizes_control_characters_and_truncates_long_strings():
    from reportlab.pdfgen.canvas import Canvas
    stream=BytesIO()
    canvas=Canvas(stream)
    printing._label(canvas,"A"*150+"\nSecond line",10,500,max_width=75)
    canvas.save()
    parsed=PdfReader(BytesIO(stream.getvalue())).pages[0].extract_text()
    assert "Second line" not in parsed
    assert "A"*30 not in parsed
    assert "A" in parsed


def test_cartographic_output_includes_point_line_multipolygon_and_labels():
    project=client.post("/projects",json={"name":"Map of mixed features"}).json()["id"]
    root=f"/projects/{project}"
    layer=client.get(root+"/workspace").json()["layers"][0]["id"]
    features=[
        {"name":"Observation","source":"Field","geometry":{"type":"Point","coordinates":[-83.,40.]},
         "properties":{"annotation":True,"annotation_text":"Monitoring station"}},
        {"name":"Road","source":"Survey","geometry":{"type":"LineString",
           "coordinates":[[-83.01,40.0],[-82.99,40.0]]}},
        {"name":"Two sites","source":"Survey","geometry":{"type":"MultiPolygon","coordinates":[
           [[[-83.006,40.001],[-83.004,40.001],[-83.004,40.003],[-83.006,40.003],[-83.006,40.001]]],
           [[[-82.996,40.001],[-82.994,40.001],[-82.994,40.003],[-82.996,40.003],[-82.996,40.001]]]
         ]}},
    ]
    for feature in features:
        reply=client.post(root+"/features",json=feature)
        assert reply.status_code==201,reply.text
    pdf=client.post(root+"/print/pdf",json={
        "title":"Mixed feature sheet","orientation":"portrait","paper":"a3",
        "extent":[-83.04,39.98,-82.96,40.04],"show_grid":False,
        "show_legend":True,"layer_ids":[layer]})
    assert pdf.status_code==200,pdf.text[:160]
    reader=PdfReader(BytesIO(pdf.content))
    text=reader.pages[0].extract_text()
    assert "Mixed feature sheet" in text
    assert "Monitoring station" in text
    assert "Features: 3" in text
    assert "LAYERS" in text


def test_map_export_rejects_inverted_extents_and_invalid_formats_without_output():
    project=client.post("/projects",json={"name":"PDF safety"}).json()["id"]
    root=f"/projects/{project}"
    for payload in (
        {"title":"  "},
        {"title":"x"*121},
        {"paper":"large-unapproved"},
        {"orientation":"rotated"},
        {"extent":[-83.,40.,-84.,41.]},
        {"extent":[-83.,40.,-82.,90.]},
    ):
        response=client.post(root+"/print/pdf",json=payload)
        assert response.status_code==422
        assert not response.content.startswith(b"%PDF")
