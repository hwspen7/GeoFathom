import pytest
from fastapi.testclient import TestClient

from core.main import app
from storage.database import StorageError, add_features, create_project, export_project, list_features

client = TestClient(app)


def sample_polygon():
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
    }


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH", str(tmp_path / "projects.sqlite"))


def test_project_lifecycle():
    project = client.post("/projects", json={"name": "Airport study"}).json()
    assert project["name"] == "Airport study"
    assert client.get("/projects").json()["total"] == 1
    feature = client.post(
        f"/projects/{project['id']}/features",
        json={"name": "Terminal", "geometry": sample_polygon(), "source": "User drawn"},
    )
    assert feature.status_code == 201
    assert feature.json()["measurement"]["area_m2"] > 1000
    features = client.get(f"/projects/{project['id']}/features").json()
    assert features["total"] == 1
    exported = client.get(f"/projects/{project['id']}/export").json()
    assert exported["type"] == "FeatureCollection"
    assert exported["features"][0]["properties"]["source"] == "User drawn"
    fid = feature.json()["id"]
    assert client.delete(f"/projects/{project['id']}/features/{fid}").status_code == 204
    assert client.get(f"/projects/{project['id']}/features").json()["total"] == 0
    assert client.delete(f"/projects/{project['id']}").status_code == 204
    assert client.get(f"/projects/{project['id']}").status_code == 404


def test_invalid_import_is_transactional():
    project = create_project("Test project")
    valid = {"type": "Feature", "geometry": sample_polygon(), "properties": {"name": "Valid"}}
    invalid = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [300, 0]}, "properties": {}}
    response = client.post(
        f"/projects/{project['id']}/import",
        json={"type": "FeatureCollection", "features": [valid, invalid]},
    )
    assert response.status_code == 422
    assert list_features(project["id"])["total"] == 0


def test_paginated_projects_and_missing_project():
    for index in range(5):
        create_project(f"Project {index}")
    response = client.get("/projects?limit=2&offset=1")
    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert len(response.json()["results"]) == 2
    assert client.get("/projects/not-found/export").status_code == 404


def test_geojson_import_and_export():
    project = create_project("Test project")
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": sample_polygon(), "properties": {"name": "One"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 1]}, "properties": {"name": "Two"}},
        ],
    }
    assert client.post(f"/projects/{project['id']}/import", json=payload).status_code == 201
    exported = export_project(project["id"])
    assert len(exported["features"]) == 2


def test_storage_handles_invalid_feature_shape():
    project = create_project("Test project")
    with pytest.raises(StorageError):
        add_features(project["id"], [{"geometry": {"type": "Point", "coordinates": [181, 0]}, "properties": {}}])
