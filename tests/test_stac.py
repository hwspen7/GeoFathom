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
