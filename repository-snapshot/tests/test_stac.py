import httpx
import pytest
from fastapi.testclient import TestClient

from core.main import app
from imagery.stac import CatalogSearchError, search_stac

client = TestClient(app)


@pytest.mark.asyncio
async def test_stac_search_fixed_endpoint_and_metadata(monkeypatch):
    calls = []
    original = httpx.AsyncClient

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature", "id": "example",
                    "collection": "sentinel-2-l2a",
                    "properties": {"datetime": "2026-01-02T12:00:00Z", "eo:cloud_cover": 5.0},
                    "bbox": [120, 31, 120.1, 31.1],
                    "links": [{"rel": "self", "href": "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/example"}],
                }
            ],
        })

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await search_stac((120.0, 31.0, 120.2, 31.2), limit=4)
    assert result["count"] == 1
    assert result["items"][0]["cloud_cover"] == 5
    assert str(calls[0].url) == "https://earth-search.aws.element84.com/v1/search"
    assert b"sentinel-2-l2a" in calls[0].content


@pytest.mark.asyncio
async def test_stac_rejects_global_and_invalid_queries():
    with pytest.raises(CatalogSearchError):
        await search_stac((-180, -90, 180, 90))
    with pytest.raises(CatalogSearchError):
        await search_stac((120, 31, 121, 32), collection="arbitrary-data")
    assert client.post("/imagery/catalog/search", json={
        "bbox": [-180, -90, 180, 90],
    }).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("bbox,limit",[
    ((0,0,0,1),8),((0,0,float("nan"),1),8),
    ((0,-91,1,1),8),((0,0,3.01,1),8),
    ((0,0,1,3.01),8),((0,0,1,1),0),((0,0,1,1),13),
])
async def test_stac_invalid_inputs_never_contact_provider(monkeypatch,bbox,limit):
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:pytest.fail("Invalid input made an HTTP request"))
    with pytest.raises(CatalogSearchError):
        await search_stac(bbox,limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload",[None,[],{"type":"wrong"},{"type":"FeatureCollection","features":{}}])
async def test_stac_malformed_envelope_returns_controlled_error(monkeypatch,payload):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:original(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload)),**kw))
    with pytest.raises(ValueError,match="invalid STAC"):
        await search_stac((0,0,1,1))


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end,expected",[
    ("2026-01-01",None,"2026-01-01/.."),
    (None,"2026-02-01","../2026-02-01"),
    ("2026-01-01","2026-02-01","2026-01-01/2026-02-01"),
])
async def test_stac_dates_and_malformed_optional_metadata(monkeypatch,start,end,expected):
    import json
    from datetime import date
    original=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content)
        assert body["datetime"]==expected
        assert body["collections"]==["sentinel-2-l1c"]
        return httpx.Response(200,json={"type":"FeatureCollection","features":[
            None,{"id":"a","properties":"invalid","links":None},
            {"id":"b","properties":{},"links":[None,"invalid",
                {"rel":"self","href":"http://example.test"},
                {"rel":"self","href":"https://example.test/item"}]},
        ]})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kw:original(
        transport=httpx.MockTransport(handler),**kw))
    result=await search_stac((0,0,1,1),"sentinel-2-l1c",3,
        date.fromisoformat(start) if start else None,date.fromisoformat(end) if end else None)
    assert result["count"]==2
    assert result["items"][0]["catalog_url"] is None
    assert result["items"][0]["cloud_cover"] is None
    assert result["items"][1]["catalog_url"]=="https://example.test/item"


@pytest.mark.asyncio
async def test_stac_reversed_date_range():
    from datetime import date
    with pytest.raises(CatalogSearchError,match="End date"):
        await search_stac((0,0,1,1),start_date=date(2026,2,1),end_date=date(2026,1,1))
