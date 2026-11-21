"""User-configured OGC WMS/WMTS/WFS and OGC API Features connectors.

HTTPS remote hosts require an explicit administrator allowlist. Requests have
bounded time/size, do not follow redirects, and never take arbitrary URL
from a viewer-side tile request. The service URL comes from SQLite config.
"""
import ipaddress
import json
import math
import os
import re
from urllib.parse import urlsplit
from uuid import uuid4
from xml.etree import ElementTree as ET

import httpx

from geometry.measure import measure_geometry,GeometryError
from storage.database import StorageError,_connect,_now,_required_project
from storage.paging import _bounds

_NAME=re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")
_SERVICES={"wms","wmts","wfs","ogc_features"}
_MAX_BYTES=5_000_000

class OGCError(ValueError):pass


def _verify_url(url):
    parsed=urlsplit(url)
    allowed={x.strip().lower() for x in os.getenv("GEOFATHOM_OGC_ALLOW_HOSTS","").split(",") if x.strip()}
    if (parsed.scheme!="https" or not parsed.hostname or
        parsed.username or parsed.password or parsed.query or parsed.fragment or
        parsed.hostname.lower() not in allowed):
        raise OGCError("OGC URL requires HTTPS and its hostname must be in GEOFATHOM_OGC_ALLOW_HOSTS.")
    hostname=parsed.hostname.lower()
    if hostname in {"localhost","metadata.google.internal"} or hostname.endswith(".local"):
        raise OGCError("Local and metadata endpoints cannot be OGC sources.")
    try:
        ip=ipaddress.ip_address(hostname)
        if not ip.is_global:raise OGCError("Private and reserved IP addresses are blocked.")
    except ValueError:
        pass
    if parsed.port is not None and parsed.port!=443:
        raise OGCError("OGC endpoints must use standard HTTPS port 443.")
    return url.rstrip("/")


def _schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS ogc_sources(
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        service TEXT NOT NULL,
        title TEXT NOT NULL,
        base_url TEXT NOT NULL,
        layer_name TEXT NOT NULL,
        attribution TEXT NOT NULL,
        tile_matrix_set TEXT NOT NULL DEFAULT 'GoogleMapsCompatible',
        created_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS ogc_sources_project_idx ON ogc_sources(project_id)")


def add_source(project_id,service,title,url,layer_name,attribution="",tile_matrix_set="GoogleMapsCompatible"):
    if service not in _SERVICES:raise OGCError("Unsupported OGC service type.")
    if not isinstance(title,str) or not 1<=len(title.strip())<=100:
        raise OGCError("OGC source title must have 1–100 characters.")
    if not _NAME.fullmatch(layer_name) or not _NAME.fullmatch(tile_matrix_set):
        raise OGCError("Invalid OGC layer or tile matrix identifier.")
    if not isinstance(attribution,str) or len(attribution)>240:
        raise OGCError("Attribution text exceeds 240 characters.")
    validated=_verify_url(url)
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        count=c.execute("SELECT count(*) FROM ogc_sources WHERE project_id=?",(project_id,)).fetchone()[0]
        if count>=30:raise OGCError("Project OGC sources are limited to 30.")
        info={"id":str(uuid4()),"project_id":project_id,"service":service,
              "title":title.strip(),"base_url":validated,"layer_name":layer_name,
              "attribution":attribution,"tile_matrix_set":tile_matrix_set,
              "created_at":_now()}
        c.execute("""INSERT INTO ogc_sources VALUES(
            :id,:project_id,:service,:title,:base_url,:layer_name,
            :attribution,:tile_matrix_set,:created_at)""",info)
        return info


def list_sources(project_id):
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        return [dict(row) for row in c.execute(
            "SELECT * FROM ogc_sources WHERE project_id=? ORDER BY created_at,id",
            (project_id,)).fetchall()]


def get_source(project_id,source_id):
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        row=c.execute("SELECT * FROM ogc_sources WHERE project_id=? AND id=?",
                      (project_id,source_id)).fetchone()
        if row is None:raise OGCError("OGC source not found.")
        info=dict(row)
    _verify_url(info["base_url"]) # Recheck allowlist every request.
    return info


def delete_source(project_id,source_id):
    with _connect() as c:
        _required_project(c,project_id);_schema(c)
        deleted=c.execute("DELETE FROM ogc_sources WHERE project_id=? AND id=?",
                          (project_id,source_id))
        if not deleted.rowcount:raise OGCError("OGC source not found.")


def _fetch(url,params,max_bytes=_MAX_BYTES):
    # Trusting system HTTP proxy settings would bypass the configured host
    # allowlist. Redirects are disabled for the same reason.
    _verify_url(url)
    try:
        with httpx.Client(timeout=httpx.Timeout(15),follow_redirects=False,
                          trust_env=False) as client:
            with client.stream("GET",url,params=params,headers={
                "User-Agent":"GeoFathom-OGC/1.0","Accept":"image/png,application/json,application/xml,text/xml",
            }) as response:
                if response.status_code!=200:
                    raise OGCError("OGC service returned HTTP "+str(response.status_code)+".")
                buf=bytearray()
                for chunk in response.iter_bytes():
                    buf.extend(chunk)
                    if len(buf)>max_bytes:
                        raise OGCError("OGC response exceeded the configured size limit.")
                return bytes(buf),response.headers.get("content-type","")
    except (httpx.TimeoutException,httpx.TransportError) as error:
        raise OGCError("OGC provider network request failed.") from error


def capabilities(project_id,source_id):
    source=get_source(project_id,source_id)
    if source["service"]=="ogc_features":
        url=source["base_url"]+"/collections"
        data,_=_fetch(url,{"f":"json"},1_000_000)
        try:
            metadata=json.loads(data)
            return {"service":"ogc_features","collections":[{
                "id":item.get("id"),"title":item.get("title") or item.get("id"),
            } for item in metadata.get("collections",[])[:100]
                if isinstance(item,dict) and isinstance(item.get("id"),str)]}
        except (ValueError,TypeError) as error:
            raise OGCError("OGC API collections document was not valid JSON.") from error
    service=source["service"].upper()
    data,_=_fetch(source["base_url"],{"SERVICE":service,"REQUEST":"GetCapabilities",
        "VERSION":{"wms":"1.3.0","wmts":"1.0.0","wfs":"2.0.0"}[source["service"]]},2_000_000)
    try:root=ET.fromstring(data)
    except ET.ParseError as error:raise OGCError("Invalid OGC Capabilities XML.") from error
    names=[]
    for node in root.iter():
        if node.tag.rsplit("}",1)[-1].lower() in {"name","identifier"} and node.text:
            value=node.text.strip()
            if _NAME.fullmatch(value) and value not in names:names.append(value)
    return {"service":source["service"],"layers":names[:100]}


def fetch_features(project_id,source_id,bbox,limit=100):
    source=get_source(project_id,source_id)
    if source["service"] not in {"wfs","ogc_features"}:
        raise OGCError("Only WFS and OGC API Features can return vector objects.")
    if not 1<=limit<=100:raise OGCError("Request 1–100 vector features.")
    west,south,east,north=_bounds(bbox)
    formatted=",".join(str(x) for x in (west,south,east,north))
    if source["service"]=="ogc_features":
        from urllib.parse import quote
        url=source["base_url"]+"/collections/"+quote(source["layer_name"],safe="")+"/items"
        params={"bbox":formatted,"limit":limit,"f":"json"}
    else:
        url=source["base_url"]
        params={"SERVICE":"WFS","VERSION":"2.0.0","REQUEST":"GetFeature",
                "TYPENAMES":source["layer_name"],"outputFormat":"application/json",
                "COUNT":limit,"SRSNAME":"EPSG:4326","BBOX":formatted+",EPSG:4326"}
    content,_=_fetch(url,params)
    try:
        obj=json.loads(content)
        if obj.get("type")!="FeatureCollection" or not isinstance(obj.get("features"),list):
            raise OGCError("OGC provider did not return a GeoJSON FeatureCollection.")
        if len(obj["features"])>limit:raise OGCError("OGC provider exceeded requested feature limit.")
        valid=[]
        for feature in obj["features"]:
            if feature.get("type")!="Feature" or not isinstance(feature.get("properties"),dict):
                raise OGCError("Invalid feature object in OGC provider response.")
            measure_geometry(feature["geometry"])
            valid.append({"type":"Feature","id":str(feature.get("id") or "")[:100],
                "geometry":feature["geometry"],"properties":{
                    str(k)[:64]:v for k,v in list(feature["properties"].items())[:100]
                    if isinstance(v,(str,int,float,bool)) or v is None,
                }})
        return {"type":"FeatureCollection","features":valid,"source_id":source_id,
            "service":source["service"],"attribution":source["attribution"],
            "truncated":len(valid)==limit}
    except (ValueError,TypeError,KeyError,GeometryError) as error:
        raise OGCError("OGC provider returned unsupported or invalid GeoJSON.") from error


def fetch_tile(project_id,source_id,z,x,y):
    source=get_source(project_id,source_id)
    if source["service"] not in {"wms","wmts"}:
        raise OGCError("Tile view is available for WMS and WMTS only.")
    if not 0<=z<=19 or not 0<=x<2**z or not 0<=y<2**z:
        raise OGCError("Invalid OGC tile coordinates.")
    if source["service"]=="wmts":
        params={"SERVICE":"WMTS","VERSION":"1.0.0","REQUEST":"GetTile",
            "LAYER":source["layer_name"],"STYLE":"default","FORMAT":"image/png",
            "TILEMATRIXSET":source["tile_matrix_set"],
            "TILEMATRIX":str(z),"TILEROW":str(y),"TILECOL":str(x)}
    else:
        extent=20037508.342789244
        side=2*extent/(2**z)
        minx=-extent+x*side;maxx=minx+side
        maxy=extent-y*side;miny=maxy-side
        params={"SERVICE":"WMS","VERSION":"1.3.0","REQUEST":"GetMap",
            "LAYERS":source["layer_name"],"STYLES":"","FORMAT":"image/png",
            "TRANSPARENT":"TRUE","CRS":"EPSG:3857","WIDTH":"256","HEIGHT":"256",
            "BBOX":",".join(str(v) for v in (minx,miny,maxx,maxy))}
    data,header=_fetch(source["base_url"],params,2_000_000)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime="image/png"
    elif data[:3]==b"\xff\xd8\xff":
        mime="image/jpeg"
    else:raise OGCError("OGC tile provider did not return a PNG/JPEG image.")
    return data,mime
