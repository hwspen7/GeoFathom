import pytest
from fastapi.testclient import TestClient

from geometry.measure import GeometryError, measure_geometry
from core.main import app

client = TestClient(app)


def rectangle() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }


def test_equatorial_square_is_geodesic() -> None:
    value = measure_geometry(rectangle())
    assert 12_000_000_000 < value["area_m2"] < 13_000_000_000
    assert 440_000 < value["perimeter_m"] < 450_000
    assert value["length_m"] is None
    assert value["method"] == "WGS84 ellipsoidal geodesic"


def test_line_length() -> None:
    value = measure_geometry({"type": "LineString", "coordinates": [[0, 0], [0, 1]]})
    assert 110_000 < value["length_m"] < 112_000
    assert value["area_m2"] is None


def test_holes_reduce_area() -> None:
    outer = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    hole = [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5], [0.5, 0.5]]
    full = measure_geometry({"type": "Polygon", "coordinates": [outer]})
    cut = measure_geometry({"type": "Polygon", "coordinates": [outer, hole]})
    assert cut["area_m2"] < full["area_m2"]


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
        {"type": "Point", "coordinates": [181, 22]},
        {"type": "GeometryCollection", "geometries": []},
        {"type": "Point", "coordinates": [float("nan"), 2]},
    ],
)
def test_invalid_geometries_are_rejected(geometry: dict) -> None:
    with pytest.raises(GeometryError):
        measure_geometry(geometry)


def test_api_measure_and_capabilities() -> None:
    assert client.get("/health").json()["status"] == "ok"
    features = client.get("/capabilities").json()
    assert features["vision_segmentation"] is True
    assert "color" in features["vision_methods"]
    assert features["imagery"] == "local_geotiff_and_public_stac_metadata"
    assert features["geodesic_measurement"] is True
    response = client.post("/measure", json={"geometry": rectangle()})
    assert response.status_code == 200
    assert response.json()["area_km2"] > 12000
    assert client.post("/vision/segment").status_code == 501


def test_api_invalid_geometry() -> None:
    response = client.post(
        "/measure", json={"geometry": {"type": "Point", "coordinates": [999, 0]}}
    )
    assert response.status_code == 422
