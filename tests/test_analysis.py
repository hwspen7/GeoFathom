import math

import pytest
from fastapi.testclient import TestClient

from analysis.operations import (
    buffer_geometry, compare_areas, distance_between_points, overlay_geometries,
)
from core.main import app
from geometry.measure import GeometryError

client = TestClient(app)


def box(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def test_wgs84_metric_buffer_approximately_matches_circle():
    result = buffer_geometry({"type": "Point", "coordinates": [0, 0]}, 1000)
    area = result["measurement"]["area_m2"]
    assert abs(area - math.pi * 1000 * 1000) / (math.pi * 1000 * 1000) < 0.01
    assert result["geometry"]["type"] == "Polygon"


def test_overlay_geometries():
    a = box(0, 0, 2, 2)
    b = box(1, 1, 3, 3)
    union = overlay_geometries(a, b, "union")
    intersection = overlay_geometries(a, b, "intersection")
    difference = overlay_geometries(a, b, "difference")
    assert intersection["measurement"]["area_m2"] < difference["measurement"]["area_m2"]
    assert union["measurement"]["area_m2"] > difference["measurement"]["area_m2"]
    empty = overlay_geometries(a, box(10, 10, 11, 11), "intersection")
    assert empty["empty"] is True
    assert empty["measurement"] is None


def test_geodesic_compare_and_distance():
    outcome = compare_areas(box(0, 0, 1, 1), box(0, 0, 2, 2))
    assert outcome["ratio"] == pytest.approx(0.25, rel=0.02)
    assert distance_between_points([0, 0], [0, 1])["distance_m"] == pytest.approx(110574, rel=0.001)


def test_bad_geo_input_is_rejected():
    with pytest.raises(GeometryError):
        buffer_geometry({"type": "Point", "coordinates": [0, 0]}, 500_000)
    with pytest.raises(GeometryError):
        overlay_geometries(
            {"type": "Point", "coordinates": [0, 0]},
            box(0, 0, 1, 1), "intersection",
        )


def test_analysis_api():
    response = client.post("/analysis/distance", json={"first": [0, 0], "second": [0, 1]})
    assert response.status_code == 200
    assert 110_000 < response.json()["distance_m"] < 112_000
    response = client.post("/analysis/compare", json={"left": box(0, 0, 1, 1), "right": box(0, 0, 2, 2)})
    assert response.status_code == 200
    assert response.json()["difference_m2"] < 0
