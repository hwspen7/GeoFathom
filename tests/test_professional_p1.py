"""P1 EPSG transformations, projected grids and graduated symbology tests."""
from math import isclose
import pytest
from fastapi.testclient import TestClient
from core.main import app

c=TestClient(app)

@pytest.fixture(autouse=True)
def db(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"crs.sqlite"))

def setup():
    p=c.post("/projects",json={"name":"CRS proof"}).json()["id"]
    root="/projects/"+p
    layer=c.get(root+"/workspace").json()["layers"][0]
    return root,layer

@pytest.mark.parametrize("method",["quantile","equal_interval","jenks"])
def test_graduated_classes_are_monotonic_and_cover_full_range(method):
    data=[i*i*0.1 for i in range(1,301)]
    r=c.post("/analysis/classify",json={"values":data,"classes":5,"method":method})
    assert r.status_code==200,r.text
    v=r.json()
    assert v["classes"]==len(v["breaks"])+1
    assert v["min"]==min(data) and v["max"]==max(data)
    assert all(a<b for a,b in zip(v["breaks"],v["breaks"][1:]))
    assert v["ranges"][0]["min"]==min(data)
    assert v["ranges"][-1]["max"]==max(data)

def test_classification_handles_duplicate_values_without_duplicate_bins():
    response=c.post("/analysis/classify",json={
        "values":[1,1,1,1,2,2,2,3,3,3],"classes":8,"method":"quantile",
    })
    assert response.status_code==200,response.text
    data=response.json()
    assert all(a<b for a,b in zip(data["breaks"],data["breaks"][1:]))

@pytest.mark.parametrize("payload",[
    {"values":[1,1,1,1],"classes":4},
    {"values":[0,1],"classes":1},
    {"values":[0,1],"classes":10},
    {"values":[0,1],"method":"bad"},
    {"values":[1]},
])
def test_bad_classification_fails_without_500(payload):
    assert c.post("/analysis/classify",json=payload).status_code==422

def test_project_crs_persists_utm_and_grid_is_wgs84():
    root,layer=setup()
    before=c.get(root+"/crs").json()
    assert before["epsg"]=="EPSG:4326" and before["revision"]==0
    write=c.put(root+"/crs",json={
        "epsg":"EPSG:32617","grid_visible":True,"expected_revision":0,
    })
    assert write.status_code==200,write.text
    assert write.json()["revision"]==1
    assert c.get(root+"/crs").json()["epsg"]=="EPSG:32617"
    grid=c.get(root+"/crs/grid",params={
        "west":-83.2,"south":39.8,"east":-82.8,"north":40.2,"divisions":5,
    })
    assert grid.status_code==200,grid.text
    assert len(grid.json()["features"])>=4
    assert grid.json()["crs"]=="EPSG:32617"
    for feature in grid.json()["features"]:
        assert feature["geometry"]["type"]=="LineString"
        assert all(-180<=p[0]<=180 and -90<=p[1]<=90
            for p in feature["geometry"]["coordinates"])

def test_coordinate_transformation_round_trip():
    root,_=setup()
    a=c.post(root+"/crs/transform",json={
        "points":[[-83.01,40.01]],"source":"EPSG:4326","target":"EPSG:26917",
    })
    assert a.status_code==200,a.text
    east,north=a.json()["coordinates"][0]
    assert 100000<east<1000000 and 1000000<north<10000000
    b=c.post(root+"/crs/transform",json={
        "points":[[east,north]],"source":"EPSG:26917","target":"EPSG:4326",
    })
    assert b.status_code==200,b.text
    lon,lat=b.json()["coordinates"][0]
    assert lon==pytest.approx(-83.01,abs=1e-5)
    assert lat==pytest.approx(40.01,abs=1e-5)

def test_crs_revision_conflict_project_isolation_and_bad_epsg():
    root,_=setup();other,_=setup()
    assert c.put(root+"/crs",json={"epsg":"EPSG:3857","expected_revision":0}).status_code==200
    assert c.put(root+"/crs",json={"epsg":"EPSG:32617","expected_revision":0}).status_code==409
    assert c.get(other+"/crs").json()["epsg"]=="EPSG:4326"
    for name in ["EPSG:banana","not-a-crs","EPSG:999999999"]:
        assert c.put(root+"/crs",json={"epsg":name}).status_code==422

def test_advanced_label_and_graduated_styles_are_revisioned():
    root,layer=setup()
    style=c.patch(root+"/layers/"+layer["id"]+"/style",json={
        "labels":{"priority":88,"offset_x":2,"offset_y":-1,
                  "placement":"line","callout":True,"prefix":"Area: ","suffix":" unit"},
        "symbol":{"graduated_field":"height",
                  "graduated_method":"jenks","graduated_breaks":[10,100],
                  "graduated_colors":["#001122","#334455","#667788"]},
    })
    assert style.status_code==200,style.text
    saved=c.get(root+"/workspace").json()["layers"][0]["style"]
    assert saved["labels"]["callout"] is True
    assert saved["labels"]["placement"]=="line"
    assert saved["symbol"]["graduated_breaks"]==[10,100]
    assert saved["symbol"]["graduated_colors"]==["#001122","#334455","#667788"]

@pytest.mark.parametrize("patch",[
    {"labels":{"priority":101}},
    {"labels":{"offset_x":11}},
    {"labels":{"placement":"expression"}},
    {"labels":{"prefix":"x"*25}},
    {"symbol":{"graduated_breaks":[10,8]}},
    {"symbol":{"graduated_breaks":[0,0]}},
    {"symbol":{"graduated_colors":["#gggggg"]}},
    {"symbol":{"graduated_breaks":[5],"graduated_colors":["#aabbcc"]}},
    {"symbol":{"graduated_method":"arbitrary-js"}},
])
def test_invalid_advanced_symbology_rejected(patch):
    root,layer=setup()
    response=c.patch(root+"/layers/"+layer["id"]+"/style",json=patch)
    assert response.status_code==422,response.text
    assert c.get(root+"/workspace").json()["layers"][0]["style_revision"]==0



@pytest.mark.parametrize("operator",["equals","contains","gte","lte","exists"])
def test_persist_attribute_label_rule_with_safe_operator(operator):
    root,layer=setup()
    response=c.patch(root+"/layers/"+layer["id"]+"/style",json={
        "labels":{
            "enabled":True,"field":"name","rule_field":"height",
            "rule_operator":operator,"rule_value":"40",
        },
    })
    assert response.status_code==200,response.text
    stored=c.get(root+"/workspace").json()["layers"][0]["style"]["labels"]
    assert stored["rule_field"]=="height"
    assert stored["rule_operator"]==operator
    assert stored["rule_value"]=="40"
    assert stored["enabled"] is True


@pytest.mark.parametrize("changes",[
    {"rule_operator":"eval"},
    {"rule_operator":"javascript"},
    {"rule_field":"x"*65},
    {"rule_value":"x"*121},
])
def test_unsafe_label_rule_rejected(changes):
    root,layer=setup()
    response=c.patch(root+"/layers/"+layer["id"]+"/style",json={
        "labels":changes,
    })
    assert response.status_code==422,response.text
    assert c.get(root+"/workspace").json()["layers"][0]["style_revision"]==0
