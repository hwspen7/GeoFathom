import pytest

from core.config import Settings
from places.discovery import DiscoveryError, _from_way, _validate_bounds, discover_features


def sample_way():
    return {
        "type": "way",
        "id": 12345,
        "tags": {"building": "yes", "name": "Test building"},
        "geometry": [
            {"lon": 0, "lat": 0},
            {"lon": 0.001, "lat": 0},
            {"lon": 0.001, "lat": 0.001},
            {"lon": 0, "lat": 0.001},
            {"lon": 0, "lat": 0},
        ],
    }


def test_way_is_measured_and_sourced():
    result = _from_way(sample_way(), "building")
    assert result["name"] == "Test building"
    assert result["source"] == "OpenStreetMap via Overpass"
    assert result["measurement"]["area_m2"] > 10_000


def test_open_way_is_not_invented_as_polygon():
    way = sample_way()
    way["geometry"] = way["geometry"][:-1]
    assert _from_way(way, "building") is None


def test_viewport_is_bounded():
    with pytest.raises(DiscoveryError):
        _validate_bounds((-1, -1, 1, 1))
    _validate_bounds((0, 0, 0.01, 0.01))


@pytest.mark.asyncio
async def test_filtering_uses_real_way_areas(monkeypatch):
    async def fake_query(bbox, category, settings):
        return [sample_way()]

    monkeypatch.setattr("places.discovery._query_overpass", fake_query)
    bbox = (0, 0, 0.01, 0.01)
    result = await discover_features(bbox, "building", 5000, None, Settings())
    assert len(result["results"]) == 1
    filtered = await discover_features(bbox, "building", 1_000_000, None, Settings())
    assert filtered["results"] == []
    assert result["truncated"] is False
