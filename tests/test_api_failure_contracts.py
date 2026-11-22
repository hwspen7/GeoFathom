"""Exercise HTTP validation, real style transactions and provider failure mapping."""
import httpx
import pytest
from fastapi.testclient import TestClient
from core.main import app
from core import access
from places import routes as places
from vision import routes as vision
from terrain import routes as terrain
from imagery.raster import RasterError

@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"api.sqlite"))
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","local")
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED","0")
    return TestClient(app)

POINT={"type":"Point","coordinates":[10,20]}
BAD={"type":"Polygon","coordinates":[]}
POLYGON={"type":"Polygon","coordinates":[[[10,20],[10.01,20],[10.01,20.01],[10,20.01],[10,20]]]}

@pytest.mark.parametrize("path,body",[
    ("/analysis/buffer",{"geometry":BAD,"distance_m":10}),
    ("/analysis/overlay",{"left":BAD,"right":POLYGON,"operation":"union"}),
    ("/analysis/compare",{"left":POINT,"right":POLYGON}),
    ("/analysis/distance",{"first":[181,20],"second":[10,20]}),
    ("/analysis/classify",{"values":[1,1,1],"classes":2}),
])
def test_analysis_invalid_geometry_and_classification(client,path,body):
    response=client.post(path,json=body)
    assert response.status_code==422,response.text
    assert isinstance(response.json()["detail"],str)

def test_graduated_style_real_transaction_and_revision_conflict(client):
    root="/projects/"+client.post("/projects",json={"name":"Graduated test"}).json()["id"]
    layer=client.get(root+"/layers").json()[0]
    for index,value in enumerate([1,4,"8",None,True,"unparseable"]):
        response=client.post(root+"/features",json={"name":str(index),
            "geometry":POLYGON,"source":"manual","properties":{"value":value}})
        assert response.status_code==201,response.text
    path=root+"/symbology/graduated"
    body={"layer_id":layer["id"],"field":"value","classes":2,"method":"equal_interval",
          "expected_revision":layer["style_revision"]}
    invalid=client.post(path,json={**body,"colors":["#ffffff"]})
    assert invalid.status_code==422,invalid.text
    response=client.post(path,json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result["classification"]["breaks"]==[4.5]
    assert result["layer"]["style"]["symbol"]["graduated_field"]=="value"
    assert client.post(path,json=body).status_code==409
    assert client.post(path,json={**body,"layer_id":"missing"}).status_code==404
    assert client.post(path,json={**body,"field":"missing"}).status_code==422

@pytest.mark.parametrize("error,status",[
    (places.DiscoveryError("Invalid bounds"),422),
    (ValueError("Bad provider payload"),503),
    (httpx.ConnectError("Offline"),503)])
def test_discovery_maps_provider_errors(client,monkeypatch,error,status):
    async def fail(*args):raise error
    monkeypatch.setattr(places,"discover_features",fail)
    response=client.post("/discover",json={"bbox":[10,20,10.01,20.01]})
    assert response.status_code==status,response.text
    assert response.json()["detail"] == ("Invalid bounds" if status==422 else
        "Spatial discovery provider unavailable. Try again later.")

@pytest.mark.parametrize("error",[ValueError("bad payload"),httpx.ConnectError("offline")])
def test_geocoder_failure_never_invents_results(client,monkeypatch,error):
    async def fail(*args):raise error
    monkeypatch.setattr(places,"search_places",fail)
    response=client.get("/search?q=Town")
    assert response.status_code==503
    assert response.json()["detail"]=="Geocoding provider unavailable. Try again later."

@pytest.mark.parametrize("route",["trace","refine"])
@pytest.mark.parametrize("error,status",[(FileNotFoundError("missing"),404),
                                      (RasterError("invalid"),422)])
def test_vision_missing_invalid_source(client,monkeypatch,route,error,status):
    def fail(*args):raise error
    monkeypatch.setattr(vision,"image_file",fail)
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED","1")
    body={"image_id":"test","longitude":10,"latitude":20} if route=="trace" else {
        "image_id":"test","positive_points":[[10,20]]}
    response=client.post("/vision/"+route,json=body)
    assert response.status_code==status,response.text

@pytest.mark.parametrize("route",["trace","refine"])
@pytest.mark.parametrize("error,status",[(vision.VisionUnavailable("model missing"),501),
                                      (RasterError("invalid pixels"),422),
                                      (ValueError("bad model result"),422)])
def test_vision_execution_errors_are_not_success(client,monkeypatch,tmp_path,route,error,status):
    monkeypatch.setenv("GEOFATHOM_SAM2_ENABLED","1")
    monkeypatch.setattr(vision,"image_file",lambda _:tmp_path/"fixture.tif")
    def fail(*args):raise error
    monkeypatch.setattr(vision,route+"_raster",fail)
    body={"image_id":"test","longitude":10,"latitude":20} if route=="trace" else {
        "image_id":"test","positive_points":[[10,20]]}
    response=client.post("/vision/"+route,json=body)
    assert response.status_code==status,response.text
    assert response.json()["detail"]==str(error)

@pytest.mark.parametrize("route",["analyze","profile"])
@pytest.mark.parametrize("error,status",[(FileNotFoundError("missing"),404),(RasterError("invalid"),422)])
def test_terrain_source_errors(client,monkeypatch,route,error,status):
    def fail(*args):raise error
    monkeypatch.setattr(terrain,"image_file",fail)
    r=client.post("/terrain/"+route,json={"image_id":"missing","geometry":POINT})
    assert r.status_code==status,r.text

@pytest.mark.parametrize("route,operation",[("analyze","analyze_area"),("profile","elevation_profile")])
def test_terrain_computation_errors(client,monkeypatch,tmp_path,route,operation):
    monkeypatch.setattr(terrain,"image_file",lambda _:tmp_path/"dem.tif")
    def fail(*args):raise RasterError("No valid DEM data")
    monkeypatch.setattr(terrain,operation,fail)
    r=client.post("/terrain/"+route,json={"image_id":"test","geometry":POINT})
    assert r.status_code==422 and r.json()["detail"]=="No valid DEM data"

def test_access_cli_lifecycle_and_revocation(client,monkeypatch,capsys):
    import sys
    project=client.post("/projects",json={"name":"Access contract"}).json()["id"]
    assert access.authenticate("x"*40) is None
    with pytest.raises(ValueError):access.create_user(" ")
    monkeypatch.setattr(sys,"argv",["access","create"," Test user "])
    access.main()
    output=capsys.readouterr().out.splitlines()
    uid=output[0].split(": ",1)[1]
    token=output[1].split(": ",1)[1]
    assert access.authenticate(token)=={"id":uid,"roles":{}}
    with pytest.raises(ValueError):access.grant(uid,project,"owner")
    with pytest.raises(ValueError):access.grant("missing",project,"viewer")
    monkeypatch.setattr(sys,"argv",["access","grant",uid,project,"viewer"])
    access.main()
    principal=access.authenticate(token)
    assert access.permits(principal,"GET",f"/projects/{project}/workspace")
    assert not access.permits(principal,"POST",f"/projects/{project}/jobs")
    access.grant(uid,project,"editor")
    principal=access.authenticate(token)
    assert access.permits(principal,"POST",f"/projects/{project}/jobs/id/cancel")
    assert access.permits(principal,"DELETE",f"/projects/{project}/features/id")
    assert not access.permits(principal,"PATCH",f"/projects/{project}/unknown")
    monkeypatch.setattr(sys,"argv",["access","revoke",uid,"--project",project])
    access.main()
    assert access.authenticate(token)["roles"]=={}
    monkeypatch.setattr(sys,"argv",["access","revoke",uid])
    access.main()
    assert access.authenticate(token) is None
