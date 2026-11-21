"""P0 cartographic PDF page and print security tests."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfbase.pdfmetrics import stringWidth
from core.main import app

c=TestClient(app)

@pytest.fixture(autouse=True)
def db(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"map.sqlite"))

def make():
    p=c.post("/projects",json={"name":"Map export"}).json()
    root="/projects/"+p["id"]
    layer=c.get(root+"/workspace").json()["layers"][0]["id"]
    for i in range(3):
        resp=c.post(root+"/features",json={
            "name":"Block "+str(i),"source":"Sample mapping",
            "layer_id":layer,
            "geometry":{"type":"Polygon","coordinates":[[
                [-83+i*.003,40],[-82.999+i*.003,40],
                [-82.999+i*.003,40.001],[-83+i*.003,40.001],
                [-83+i*.003,40],
            ]]},
        })
        assert resp.status_code==201,resp.text
    return root,layer

def export(root,**changes):
    return c.post(root+"/print/pdf",json={"title":"Professional map",
                        "paper":"a4","orientation":"landscape",**changes})

def test_pdf_vector_layout_contains_page_map_scale_and_layer_names():
    root,layer=make()
    r=export(root,show_legend=True,show_grid=True)
    assert r.status_code==200,r.text[:100]
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")
    from pypdf import PdfReader
    doc=PdfReader(BytesIO(r.content))
    assert len(doc.pages)==1
    text=doc.pages[0].extract_text()
    assert "Professional map" in text
    assert "LAYERS" in text
    assert "Measurements" in text
    assert "WGS84" in text
    assert "N" in text
    assert "Map geometry does not establish" in text

@pytest.mark.parametrize("paper,orientation",[
    ("a4","portrait"),("a4","landscape"),("a3","portrait"),
    ("a3","landscape"),("letter","portrait"),("letter","landscape"),
])
def test_print_page_dimensions_and_orientation(paper,orientation):
    root,layer=make()
    r=export(root,paper=paper,orientation=orientation,show_legend=False)
    assert r.status_code==200,r.text[:120]
    from pypdf import PdfReader
    page=PdfReader(BytesIO(r.content)).pages[0]
    width,height=float(page.mediabox.width),float(page.mediabox.height)
    assert (width>height)==(orientation=="landscape")

def test_print_hides_locked_or_invisible_layers():
    root,layer=make()
    assert c.patch(root+"/layers/"+layer,json={"visible":False}).status_code==200
    r=export(root,extent=[-83.05,39.95,-82.9,40.1])
    assert r.status_code==200
    from pypdf import PdfReader
    text=PdfReader(BytesIO(r.content)).pages[0].extract_text()
    assert "Features: 0" in text
    assert "Measurements" not in text

@pytest.mark.parametrize("changes",[
    {"paper":"poster"},
    {"orientation":"upside-down"},
    {"title":" "},
    {"title":"A"*121},
    {"extent":[-180,0,180,10]},
    {"extent":[10,20,0,30]},
    {"extent":[0,-90,5,10]},
    {"extent":[0,0,100,10]},
    {"layer_ids":["not-a-layer"]},
])
def test_invalid_layout_cannot_generate_pdf(changes):
    root,layer=make()
    assert export(root,**changes).status_code==422

def test_empty_project_requires_extent():
    p=c.post("/projects",json={"name":"Blank"}).json()["id"]
    root="/projects/"+p
    assert export(root).status_code==422
    assert export(root,extent=[-1,-1,1,1]).status_code==200

def test_no_cross_project_map_leak():
    root,layer=make()
    other=c.post("/projects",json={"name":"Other"}).json()["id"]
    r=c.post("/projects/"+other+"/print/pdf",json={
        "title":"Other","layer_ids":[layer],"extent":[-84,39,-82,41]})
    assert r.status_code==404
