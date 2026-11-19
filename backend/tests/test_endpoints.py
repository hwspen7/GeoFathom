from fastapi.testclient import TestClient

from app.geocoding import _place
from app.main import app

client = TestClient(app)


def test_nominatim_location_only_is_not_polygon() -> None:
    record = {
        "osm_type": "node",
        "osm_id": 42,
        "name": "Sample landmark",
        "display_name": "Sample landmark, Sample city",
        "lon": "12.4",
        "lat": "56.7",
        "boundingbox": ["56.6", "56.8", "12.3", "12.5"],
        "geojson": {"type": "Point", "coordinates": [12.4, 56.7]},
    }
    result = _place(record)
    assert result["bbox"] == [12.3, 56.6, 12.5, 56.8]
    assert result["geometry"] is None
    assert result["boundary_status"] == "location_only"


def test_search_and_assistant_with_stubbed_geocoder(monkeypatch) -> None:
    record = {
        "id": "osm:node:42",
        "name": "Sample",
        "display_name": "Sample",
        "longitude": 12.4,
        "latitude": 56.7,
        "bbox": None,
        "geometry": None,
        "boundary_status": "location_only",
        "source": "OpenStreetMap via Nominatim",
        "osm_type": "node",
        "osm_id": 42,
    }

    async def fake_search(query, settings, limit=5):
        return [record]

    monkeypatch.setattr("app.main.search_places", fake_search)
    result = client.get("/search?q=Sample")
    assert result.status_code == 200
    assert result.json()["results"][0]["boundary_status"] == "location_only"

    answer = client.post("/assistant", json={"message": "Find Sample"})
    assert answer.status_code == 200
    assert answer.json()["measurement"] is None
    assert "no usable mapped boundary" in answer.json()["message"]


def test_spatial_discovery_does_not_fabricate_results() -> None:
    response = client.post(
        "/assistant", json={"message": "寻找面积超过20000平方米的建筑"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_supported"
    assert response.json()["results"] == []
