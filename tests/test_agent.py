import pytest
from fastapi.testclient import TestClient

from core.main import app
from intelligence.agent import _area_filters, _category

client = TestClient(app)


def test_area_filters_are_in_square_meters():
    assert _area_filters("寻找面积超过2公顷的建筑")[0] == 20_000
    assert _area_filters("find buildings at least 5000 square meters")[0] == 5000
    assert _area_filters("寻找面积最多1平方公里的绿地")[1] == 1_000_000


def test_feature_classification():
    assert _category("寻找水域") == "water"
    assert _category("Find buildings above 1 ha") == "building"
    assert _category("寻找绿地") == "landuse"


def test_agent_needs_viewport_for_discovery():
    response = client.post("/assistant", json={"message": "寻找面积超过20000平方米的建筑"})
    assert response.status_code == 200
    assert response.json()["status"] == "not_supported"
    assert response.json()["results"] == []


def test_agent_invalid_large_viewport_does_not_search():
    response = client.post(
        "/assistant",
        json={"message": "寻找面积超过20000平方米的建筑", "bbox": [-1, -1, 1, 1]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "needs_viewport"


def test_agent_proximity_filter_is_not_misrepresented():
    response = client.post(
        "/assistant",
        json={"message": "寻找距离公路2公里以内的建筑", "bbox": [0, 0, 0.01, 0.01]},
    )
    assert response.json()["status"] == "not_supported"


def test_agent_queries_bounded_spatial_search(monkeypatch):
    requests = []

    async def fake_discover(bbox, category, minimum, maximum, settings):
        requests.append((bbox, category, minimum, maximum))
        return {"results": [], "source": "OpenStreetMap via Overpass", "warning": "Not exhaustive.", "truncated": False}

    monkeypatch.setattr("intelligence.agent.discover_features", fake_discover)
    response = client.post(
        "/assistant",
        json={"message": "寻找面积超过5000平方米的建筑", "bbox": [0, 0, 0.01, 0.01]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"
    assert requests[0][1:3] == ("building", 5000)
    assert response.json()["steps"][-1]["tool"] == "discover_features"


def test_tools_announce_vision_unavailable():
    response = client.get("/assistant/tools")
    assert response.status_code == 200
    assert any(item["name"] == "satellite_segmentation" and not item["ready"] for item in response.json()["tools"])
