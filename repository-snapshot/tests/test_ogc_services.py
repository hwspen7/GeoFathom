"""Research trusted OGC service integration, tile proxy security and validation."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from core.main import app
from services import ogc

c=TestClient(app)
png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/ZecAAAAASUVORK5CYII=")

@pytest.fixture(autouse=True)
def config(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"ogc.sqlite"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN","administrator-proof")
    monkeypatch.setenv("GEOFATHOM_OGC_ALLOW_HOSTS","maps.example.org")

def make():
    item=c.post("/projects",json={"name":"OGC test"}).json()
    return "/projects/"+item["id"]

def source(root,service="wms",url="https://maps.example.org/ows",name="sample"):
    return c.post(root+"/ogc",json={
        "service":service,"title":"Remote source","base_url":url,
        "layer_name":name,"attribution":"Public map data",
        "tile_matrix_set":"GoogleMapsCompatible",
    },headers={"X-GeoFathom-Admin-Token":"administrator-proof"})

def test_ogc_registration_is_admin_only_and_project_scoped():
    root=make();other=make()
    no_auth=c.post(root+"/ogc",json={
        "service":"wms","title":"A","base_url":"https://maps.example.org/ows",
        "layer_name":"sample"})
    assert no_auth.status_code==403
    created=source(root)
    assert created.status_code==201,created.text
    uid=created.json()["id"]
    assert c.get(root+"/ogc").json()["sources"][0]["id"]==uid
    assert c.get(other+"/ogc").json()["sources"]==[]
    assert c.get(other+"/ogc/"+uid+"/capabilities").status_code==404
    assert c.delete(root+"/ogc/"+uid).status_code==403
    assert c.delete(root+"/ogc/"+uid,headers={
        "X-GeoFathom-Admin-Token":"administrator-proof"}).status_code==204
    assert c.get(root+"/ogc").json()["sources"]==[]

@pytest.mark.parametrize("url",[
    "http://maps.example.org/ows",
    "https://127.0.0.1/ows",
    "https://localhost/ows",
    "https://169.254.169.254/latest/meta-data",
    "https://maps.example.org:8888/ows",
    "https://maps.example.org/ows?secret=xyz",
    "https://admin:pass@maps.example.org/ows",
    "https://unapproved.example.org/ows",
    "file:///etc/passwd",
])
def test_ogc_url_policy_rejects_ssrf_and_unapproved_endpoints(url):
    root=make()
    assert source(root,url=url).status_code==422

def test_wms_tile_proxy_builds_projected_3857_bbox(monkeypatch):
    root=make();sid=source(root).json()["id"]
    observed={}
    def fake(url,params,max_bytes=5_000_000):
        observed.update(params)
        assert url=="https://maps.example.org/ows"
        return png,"image/png"
    monkeypatch.setattr(ogc,"_fetch",fake)
    r=c.get(root+"/ogc/"+sid+"/tiles/3/2/3")
    assert r.status_code==200,r.text[:100]
    assert r.headers["content-type"]=="image/png"
    assert observed["SERVICE"]=="WMS"
    assert observed["CRS"]=="EPSG:3857"
    assert len(observed["BBOX"].split(","))==4
    assert observed["WIDTH"]=="256"
    assert c.get(root+"/ogc/"+sid+"/tiles/3/16/0").status_code==422

def test_wmts_kvp_tile_matrix_and_coordinates(monkeypatch):
    root=make();sid=source(root,service="wmts").json()["id"]
    observed={}
    monkeypatch.setattr(ogc,"_fetch",lambda url,params,max_bytes=5_000_000:
                        (observed.update(params) or png,"image/png"))
    r=c.get(root+"/ogc/"+sid+"/tiles/4/8/2")
    assert r.status_code==200,r.text[:100]
    assert observed["SERVICE"]=="WMTS"
    assert observed["TILEMATRIX"]=="4"
    assert observed["TILECOL"]=="8"
    assert observed["TILEROW"]=="2"

def test_ogc_api_feature_collection_read_only_preview(monkeypatch):
    root=make();sid=source(root,service="ogc_features",
                          url="https://maps.example.org",name="parcels").json()["id"]
    calls=[]
    def fake(url,params,max_bytes=5_000_000):
        calls.append((url,params))
        response={"type":"FeatureCollection","features":[{
            "type":"Feature","id":"north","geometry":{
                "type":"Point","coordinates":[-83,40]},
            "properties":{"name":"North Site","height":22.2},
        }]}
        return json.dumps(response).encode(),"application/json"
    monkeypatch.setattr(ogc,"_fetch",fake)
    r=c.get(root+"/ogc/"+sid+"/features",params={
        "west":-84,"south":39,"east":-82,"north":41,"limit":5})
    assert r.status_code==200,r.text
    assert r.json()["features"][0]["properties"]["name"]=="North Site"
    assert calls[0][0].endswith("/collections/parcels/items")
    assert calls[0][1]["bbox"]=="-84.0,39.0,-82.0,41.0"

def test_wfs_geojson_and_capabilities(monkeypatch):
    root=make();sid=source(root,service="wfs").json()["id"]
    def fake(url,params,max_bytes=5_000_000):
        if params["REQUEST"]=="GetCapabilities":
            return b'<WFS_Capabilities><Name>Roads</Name></WFS_Capabilities>',"text/xml"
        return b'{"type":"FeatureCollection","features":[]}',"application/json"
    monkeypatch.setattr(ogc,"_fetch",fake)
    info=c.get(root+"/ogc/"+sid+"/capabilities")
    assert info.status_code==200
    assert "Roads" in info.json()["layers"]
    r=c.get(root+"/ogc/"+sid+"/features",params={
        "west":-84,"south":39,"east":-82,"north":41})
    assert r.status_code==200 and r.json()["features"]==[]

def test_ogc_invalid_service_payloads_are_not_inserted(monkeypatch):
    root=make();sid=source(root,service="wfs").json()["id"]
    monkeypatch.setattr(ogc,"_fetch",lambda url,params,max_bytes=5_000_000:
                        (b"<html>not geojson</html>","text/html"))
    r=c.get(root+"/ogc/"+sid+"/features",params={
        "west":-84,"south":39,"east":-82,"north":41})
    assert r.status_code==422
    assert c.get(root+"/features").json()["total"]==0


@pytest.mark.parametrize("field,value",[
    ("service","not-a-service"),("title",""),
    ("title","x"*101),("layer_name","spaces not allowed"),
    ("tile_matrix_set","invalid !"),("attribution","x"*241),
])
def test_source_rejects_invalid_admin_configuration(field,value):
    root=make()
    payload={"service":"wms","title":"Remote source",
             "base_url":"https://maps.example.org/ows",
             "layer_name":"sample","attribution":"public",
             "tile_matrix_set":"GoogleMapsCompatible"}
    payload[field]=value
    denied=c.post(root+"/ogc",json=payload,headers={
        "X-GeoFathom-Admin-Token":"administrator-proof"})
    assert denied.status_code==422
    assert c.get(root+"/ogc").json()["sources"]==[]


@pytest.mark.parametrize("url",[
    "https://localhost/ows","https://metadata.google.internal/ows",
    "https://tenant.local/ows","https://192.168.1.50/ows",
    "https://10.0.0.1/ows","https://maps.example.org:8443/ows",
])
def test_ogc_allowlist_cannot_override_private_network_rules(monkeypatch,url):
    from urllib.parse import urlsplit
    monkeypatch.setenv("GEOFATHOM_OGC_ALLOW_HOSTS",urlsplit(url).hostname)
    with pytest.raises(ogc.OGCError):
        ogc._verify_url(url)


def test_allowlist_is_rechecked_after_saved_source_creation(monkeypatch):
    root=make();uid=source(root).json()["id"]
    monkeypatch.setenv("GEOFATHOM_OGC_ALLOW_HOSTS","unrelated.example.org")
    assert c.get(root+"/ogc/"+uid+"/capabilities").status_code==422
    assert len(c.get(root+"/ogc").json()["sources"])==1


def test_ogc_api_collections_are_parsed_and_bounded(monkeypatch):
    root=make();uid=source(root,service="ogc_features",
                           url="https://maps.example.org",name="roads").json()["id"]
    observed=[]
    def fake(url,params,max_bytes=5_000_000):
        observed.append((url,params,max_bytes))
        return json.dumps({"collections":[
            {"id":"roads","title":"Public roads"},
            {"id":"water"}, {"id":34},{"title":"no identifier"},
            "not a mapping"]}).encode(),"application/json"
    monkeypatch.setattr(ogc,"_fetch",fake)
    result=c.get(root+"/ogc/"+uid+"/capabilities")
    assert result.status_code==200,result.text
    assert result.json()["collections"]==[
        {"id":"roads","title":"Public roads"},{"id":"water","title":"water"}]
    assert observed==[("https://maps.example.org/collections",{"f":"json"},1_000_000)]
    monkeypatch.setattr(ogc,"_fetch",
        lambda *args,**kwargs:(b"unparseable json","application/json"))
    assert c.get(root+"/ogc/"+uid+"/capabilities").status_code==422


def test_invalid_capabilities_xml_is_rejected_without_polluting_project(monkeypatch):
    root=make();uid=source(root).json()["id"]
    monkeypatch.setattr(ogc,"_fetch",
        lambda *args,**kwargs:(b"<capabilities>","application/xml"))
    assert c.get(root+"/ogc/"+uid+"/capabilities").status_code==422
    assert c.get(root+"/features").json()["total"]==0


@pytest.mark.parametrize("payload",[
    {"type":"FeatureCollection","features":{}},
    {"type":"FeatureCollection","features":[{"type":"Other","properties":{}}]},
    {"type":"FeatureCollection","features":[{"type":"Feature","properties":[]}]},
    {"type":"FeatureCollection","features":[
        {"type":"Feature","geometry":{"type":"Point","coordinates":[0,0]},
         "properties":{}}]*3},
])
def test_invalid_wfs_feature_collections_are_rejected(monkeypatch,payload):
    root=make();uid=source(root,service="wfs").json()["id"]
    monkeypatch.setattr(ogc,"_fetch",
        lambda *args,**kwargs:(json.dumps(payload).encode(),"application/json"))
    response=c.get(root+"/ogc/"+uid+"/features",params={
        "west":-84,"south":39,"east":-82,"north":41,"limit":2})
    assert response.status_code==422,response.text
    assert c.get(root+"/features").json()["total"]==0


def test_wfs_feature_properties_are_sanitized_without_mutating_source(monkeypatch):
    root=make();uid=source(root,service="wfs").json()["id"]
    fields={"numeric":12,"floating":2.5,"present":True,"null":None,
            "private":["not exposed"],"too_long_"+"x"*100:"short"}
    item={"type":"Feature","id":"x"*102,
          "geometry":{"type":"Point","coordinates":[-83,40]},
          "properties":fields}
    monkeypatch.setattr(ogc,"_fetch",
        lambda *args,**kwargs:(json.dumps({"type":"FeatureCollection",
             "features":[item]}).encode(),"application/json"))
    response=c.get(root+"/ogc/"+uid+"/features",params={
        "west":-84,"south":39,"east":-82,"north":41,"limit":1})
    assert response.status_code==200,response.text
    body=response.json()
    assert body["truncated"] is True
    feature=body["features"][0]
    assert len(feature["id"])==100
    assert "private" not in feature["properties"]
    assert feature["properties"]["numeric"]==12
    assert feature["properties"]["null"] is None
    assert all(len(key)<=64 for key in feature["properties"])


@pytest.mark.parametrize("data,expected",[
    (b"not a real image",422),(b"\xff\xd8\xffjpeg-body",200)
])
def test_tile_proxy_validates_encoded_image_magic(monkeypatch,data,expected):
    root=make();uid=source(root,service="wms").json()["id"]
    monkeypatch.setattr(ogc,"_fetch",lambda *args,**kwargs:(data,"application/octet-stream"))
    response=c.get(root+"/ogc/"+uid+"/tiles/2/1/1")
    assert response.status_code==expected
    if expected==200:assert response.headers["content-type"]=="image/jpeg"


def test_ogc_network_request_bounds_redirects_http_status_and_transport(monkeypatch):
    import httpx
    original=httpx.Client
    observed=[]
    def send(request):
        observed.append((str(request.url),request.headers["user-agent"]))
        action=request.url.params.get("probe")
        if action=="status":return httpx.Response(503)
        if action=="big":return httpx.Response(200,content=b"123456789")
        if action=="timeout":raise httpx.ConnectTimeout("Provider timed out.")
        return httpx.Response(200,content=b"PNG",headers={"content-type":"image/png"})
    transport=httpx.MockTransport(send)
    monkeypatch.setattr(ogc.httpx,"Client",
        lambda *args,**kwargs:original(transport=transport,**kwargs))
    path="https://maps.example.org/ows"
    assert ogc._fetch(path,{"probe":"normal"})==(b"PNG","image/png")
    with pytest.raises(ogc.OGCError,match="HTTP 503"):
        ogc._fetch(path,{"probe":"status"})
    with pytest.raises(ogc.OGCError,match="size limit"):
        ogc._fetch(path,{"probe":"big"},max_bytes=4)
    with pytest.raises(ogc.OGCError,match="network"):
        ogc._fetch(path,{"probe":"timeout"})
    assert len(observed)==4
    assert all(label=="GeoFathom-OGC/1.0" for _,label in observed)
