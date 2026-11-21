"""GIS format interchange and declared coordinate system re-projection."""
from io import BytesIO
import json
import zipfile

import numpy as np
import pyogrio
import pytest
import shapely
from fastapi.testclient import TestClient
from core.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"vectors.sqlite"))


def setup():
    project=client.post("/projects",json={"name":"Interchange"}).json()
    return "/projects/"+project["id"]


def test_gpkg_import_reprojects_to_wgs84(tmp_path):
    root=setup()
    path=tmp_path/"projected.gpkg"
    pyogrio.raw.write(path,np.array([shapely.to_wkb(shapely.Point(1000,1000))],dtype=object),
                      [np.array(["Sensor"],dtype=object)],["name"],
                      driver="GPKG",crs="EPSG:3857",geometry_type="Point")
    r=client.post(root+"/vector/import",files={"file":("point.gpkg",path.read_bytes())})
    assert r.status_code==201,r.text
    assert r.json()["count"] if "count" in r.json() else r.json()["created"]==1
    result=client.get(root+"/features").json()["results"][0]
    assert 0.008<result["geometry"]["coordinates"][0]<0.010
    assert result["properties"]["name"]=="Sensor"


def test_geojson_and_geopackage_export(tmp_path):
    root=setup()
    geo={"type":"Point","coordinates":[4.2,51.2]}
    saved=client.post(root+"/features",json={"name":"Site","geometry":geo,"source":"test"})
    assert saved.status_code==201
    exported=client.get(root+"/vector/export/geojson")
    assert exported.status_code==200
    assert json.loads(exported.content)["features"][0]["geometry"]==geo
    gpkg=client.get(root+"/vector/export/gpkg")
    assert gpkg.status_code==200,gpkg.text[:200]
    output=tmp_path/"out.gpkg"
    output.write_bytes(gpkg.content)
    meta,*rest=pyogrio.raw.read(output)
    assert meta["crs"]


def test_zipped_shapefile_import_and_zip_slip_rejection(tmp_path):
    root=setup()
    from storage.vectorio import read_vector,VectorIOError
    malicious=BytesIO()
    with zipfile.ZipFile(malicious,"w") as z:
        z.writestr("../escape.shp",b"bad")
    with pytest.raises(VectorIOError):
        read_vector("bad.zip",malicious.getvalue())
    assert client.post(root+"/vector/import",files={"file":("x.zip",malicious.getvalue())}).status_code==422



def test_shapefile_zip_round_trip(tmp_path):
    root=setup()
    polygon={"type":"Polygon","coordinates":[[[2,2],[3,2],[3,3],[2,3],[2,2]]]}
    assert client.post(root+"/features",json={
        "name":"Plot","geometry":polygon,"source":"Original",
    }).status_code==201
    exported=client.get(root+"/vector/export/shapefile")
    assert exported.status_code==200,exported.text[:150]
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        filenames=archive.namelist()
        assert any(name.endswith(".shp") for name in filenames)
        assert any(name.endswith(".prj") for name in filenames)
    other=setup()
    imported=client.post(other+"/vector/import",
                         files={"file":("parcel.zip",exported.content,"application/zip")})
    assert imported.status_code==201,imported.text
    assert imported.json()["created"]==1
    geom=client.get(other+"/features").json()["results"][0]["geometry"]
    assert geom["type"]=="Polygon"


def test_kml_polygon_round_trip():
    root=setup()
    polygon={"type":"Polygon","coordinates":[
        [[2,2],[3,2],[3,3],[2,3],[2,2]],
    ]}
    assert client.post(root+"/features",json={
        "name":"KML Plot","geometry":polygon,"source":"Original",
    }).status_code==201
    exported=client.get(root+"/vector/export/kml")
    assert exported.status_code==200,exported.text[:200]
    assert b"<kml" in exported.content
    other=setup()
    imported=client.post(other+"/vector/import",files={"file":("plot.kml",exported.content)})
    assert imported.status_code==201,imported.text
    assert imported.json()["created"]>=1


def test_gpx_track_and_waypoint_round_trip():
    root=setup()
    line={"type":"LineString","coordinates":[[2,2],[2.001,2],[2.002,2.001]]}
    assert client.post(root+"/features",json={
        "name":"Track","geometry":line,"source":"Recorded",
    }).status_code==201
    exported=client.get(root+"/vector/export/gpx")
    assert exported.status_code==200,exported.text[:200]
    assert b"<trk>" in exported.content
    other=setup()
    imported=client.post(other+"/vector/import",files={"file":("track.gpx",exported.content)})
    assert imported.status_code==201,imported.text
    assert imported.json()["created"]>=1
    assert any(item["geometry"]["type"] in {"LineString","MultiLineString"}
               for item in client.get(other+"/features").json()["results"])


def test_gpx_rejects_polygon_export():
    root=setup()
    polygon={"type":"Polygon","coordinates":[[[0,0],[.01,0],[.01,.01],[0,0]]]}
    assert client.post(root+"/features",json={"name":"Area","geometry":polygon}).status_code==201
    response=client.get(root+"/vector/export/gpx")
    assert response.status_code==422
