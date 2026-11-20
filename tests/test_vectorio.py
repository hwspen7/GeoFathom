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
