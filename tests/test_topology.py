import pytest

from geometry.measure import GeometryError
from geometry.topology import bbox_overlaps, contains_point, native_available


def square():
    return {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        ],
    }


def test_contains_point_and_excludes_edges():
    assert contains_point(square(), 1, 1)
    assert not contains_point(square(), 3, 1)
    assert not contains_point(square(), 0, 1)


def test_holes_are_excluded():
    item = square()
    item["coordinates"].append(
        [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5], [0.5, 0.5]]
    )
    assert not contains_point(item, 1, 1)
    assert contains_point(item, 0.25, 0.25)


def test_bbox_intersection():
    assert bbox_overlaps([0, 0, 2, 2], [2, 1, 4, 3])
    assert not bbox_overlaps([0, 0, 2, 2], [3, 3, 4, 4])


def test_invalid_input_is_rejected():
    with pytest.raises(GeometryError):
        contains_point({"type": "Point", "coordinates": [0, 0]}, 0, 0)
    with pytest.raises(GeometryError):
        bbox_overlaps([2, 2, 0, 0], [0, 0, 1, 1])


def test_native_capability_is_explicit():
    assert isinstance(native_available(), bool)

import os
from fastapi.testclient import TestClient
from core.main import app


def test_spatial_api_contains_and_bbox():
    client = TestClient(app)
    result = client.post(
        "/spatial/contains",
        json={"geometry": square(), "longitude": 1, "latitude": 1},
    )
    assert result.status_code == 200
    assert result.json()["inside"] is True
    assert client.post(
        "/spatial/bbox-overlap",
        json={"first": [0, 0, 1, 1], "second": [2, 2, 3, 3]},
    ).json()["overlaps"] is False


def test_native_is_loaded_in_compiled_ci():
    if os.getenv("GEOFATHOM_REQUIRE_NATIVE") == "1":
        assert native_available()
