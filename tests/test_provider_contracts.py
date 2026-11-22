"""Exercise real HTTP request construction and provider responses without live network."""
import asyncio
from collections import OrderedDict
from dataclasses import replace

import httpx
import pytest

from core.config import Settings
from places import geocoding as geo, discovery as disc


@pytest.fixture
def providers(monkeypatch):
    original=httpx.AsyncClient
    responses=[]
    requests=[]
    sleeps=[]
    clock=[1000.]
    def dispatch(request):
        requests.append(request)
        status,body=responses.pop(0)
        return httpx.Response(status,json=body)
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:original(
        transport=httpx.MockTransport(dispatch),**kw))
    # Use private module clocks, not the event loop's global clock.
    from types import SimpleNamespace
    for module,cache,lock,last in (
        (geo,"_cache","_lock","_last_request"),
        (disc,"_CACHE","_LOCK","_LAST_REQUEST")):
        monkeypatch.setattr(module,cache,OrderedDict())
        monkeypatch.setattr(module,lock,asyncio.Lock())
        monkeypatch.setattr(module,last,0.)
        monkeypatch.setattr(module,"time",SimpleNamespace(monotonic=lambda:clock[0]))
    # Provider delay is observable without making tests wait for public quotas.
    async def sleep(seconds):
        sleeps.append(seconds)
        clock[0]+=seconds
    for module in (geo,disc):
        monkeypatch.setattr(module,"asyncio",SimpleNamespace(sleep=sleep))
    return responses,requests,sleeps,clock


@pytest.mark.asyncio
async def test_geocoder_cache_expiry_throttle_and_mapping(providers):
    responses,requests,sleeps,clock=providers
    settings=replace(Settings(),contact_email="operator@example.test")
    polygon={"type":"Polygon","coordinates":[[[10,20],[11,20],[11,21],[10,20]]]}
    responses.append((200,[{"lon":"10","lat":"20","osm_type":"way","osm_id":7,
        "boundingbox":["20","21","10","11"],"display_name":"Town, Country",
        "geojson":polygon}, {"lon":"12","lat":"22","name":"Station","geojson":{"type":"Point"}},None]))
    first=await geo.search_places("Town",settings,4)
    assert first[0]["bbox"]==[10,20,11,21] and first[0]["geometry"]==polygon
    assert first[0]["name"]=="Town" and first[0]["boundary_status"]=="mapped"
    assert first[1]["boundary_status"]=="location_only" and first[1]["geometry"] is None
    assert requests[0].url.params["limit"]=="4"
    assert "operator@example.test" in requests[0].headers["User-Agent"]
    assert await geo.search_places(" town ",settings,4)==first and len(requests)==1
    responses.append((200,[]))
    assert await geo.search_places("Different",settings)==[]
    assert sleeps==[pytest.approx(1.05)]
    clock[0]+=3601
    responses.append((200,[]))
    assert not await geo.search_places("Town",settings,4)
    assert len(requests)==3


@pytest.mark.asyncio
async def test_geocoder_errors_do_not_cache_and_cache_capacity(providers):
    responses,requests,_,clock=providers
    settings=Settings()
    responses.extend([(503,{}),(200,{"wrong":1}),(200,[])])
    with pytest.raises(httpx.HTTPStatusError):
        await geo.search_places("bad",settings)
    with pytest.raises(ValueError,match="Unexpected"):
        await geo.search_places("bad",settings)
    assert await geo.search_places("bad",settings)==[]
    assert "set GEOFATHOM_CONTACT_EMAIL" in requests[-1].headers["User-Agent"]
    for i in range(128):
        geo._cache[str(i)]=(clock[0],[])
    responses.append((200,[]))
    await geo.search_places("new",settings)
    assert len(geo._cache)==128 and "0" not in geo._cache


def way(size,uid):
    return {"type":"way","id":uid,"geometry":[
        {"lon":10+x,"lat":20+y} for x,y in (
            (0,0),(size,0),(size,size),(0,size),(0,0))]}


@pytest.mark.asyncio
async def test_overpass_real_query_cache_and_bounded_results(providers,monkeypatch):
    responses,requests,sleeps,clock=providers
    settings=Settings()
    bbox=(10.,20.,10.03,20.03)
    responses.append((200,{"elements":[way(.001,1),way(.002,2),{"type":"node"},way(.003,3)]}))
    monkeypatch.setattr(disc,"_MAX_RESULTS",2)
    result=await disc.discover_features(bbox,"building",0,None,settings)
    assert result["checked"]==4 and result["truncated"]
    assert [item["osm_id"] for item in result["results"]]==[3,2]
    assert 'way%5B%22building%22%5D' in requests[0].content.decode()
    smaller=await disc.discover_features(bbox,"building",0,20000,settings)
    assert [item["osm_id"] for item in smaller["results"]]==[1]
    assert len(requests)==1
    responses.append((200,{"elements":[]}))
    assert not (await disc.discover_features(bbox,"water",0,None,settings))["results"]
    assert sleeps==[2.]
    clock[0]+=901
    responses.append((200,{"elements":None}))
    with pytest.raises(ValueError,match="Invalid Overpass"):
        await disc.discover_features(bbox,"building",0,None,settings)
    assert len(requests)==3


@pytest.mark.parametrize("bbox,category,low,high",[
    ((0,0,float("nan"),1),"building",0,None),
    ((1,0,0,.01),"building",0,None),
    ((0,0,1,1),"building",0,None),
    ((0,0,.01,.01),"unsupported",0,None),
    ((0,0,.01,.01),"water",-1,None),
    ((0,0,.01,.01),"water",10,5),
])
@pytest.mark.asyncio
async def test_discovery_rejects_unbounded_or_invalid_queries(providers,bbox,category,low,high):
    with pytest.raises(disc.DiscoveryError):
        await disc.discover_features(bbox,category,low,high,Settings())
    assert not providers[1]
