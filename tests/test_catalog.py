"""Model catalog persistence and API guardrails, with no real cloud requests."""

import json

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from core.main import app
from intelligence.catalog import (
    CatalogError, ModelSpec, list_public, model_spec, provider_for_spec,
    save_spec, select_default,
)
import intelligence.routes as routes

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFATHOM_MODEL_CATALOG_PATH", str(tmp_path / "models.json"))
    monkeypatch.setenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "test-admin-secret")


def custom_cloud():
    return {
        "id": "remote-custom", "name": "Custom hosted model",
        "provider": "openai-compatible", "model": "my-large-model",
        "base_url": "https://example.org/v1",
        "credential_env": "GEOFATHOM_MODEL_KEY_CUSTOM", "enabled": True,
    }


def test_three_presets_and_local_first():
    data = client.get("/models/catalog").json()
    assert data["default_id"] == "local-saluki"
    assert [item["id"] for item in data["models"]] == [
        "local-saluki", "cloud-groq", "cloud-gemini"
    ]
    assert all(item["preset"] for item in data["models"])
    assert all("api_key" not in item for item in data["models"])


def test_model_configuration_requires_admin_token():
    request = custom_cloud()
    assert client.put("/models/catalog/remote-custom", json=request).status_code == 403
    assert client.put(
        "/models/catalog/remote-custom", json=request,
        headers={"X-GeoFathom-Admin-Token": "wrong"},
    ).status_code == 403


def test_create_modify_select_delete_custom_model(monkeypatch):
    request = custom_cloud()
    admin = {"X-GeoFathom-Admin-Token": "test-admin-secret"}
    created = client.put("/models/catalog/remote-custom", json=request, headers=admin)
    assert created.status_code == 200
    assert len(created.json()["models"]) == 4
    assert created.json()["models"][-1]["configured"] is False
    monkeypatch.setenv("GEOFATHOM_MODEL_KEY_CUSTOM", "mock-credential")
    assert client.get("/models/catalog").json()["models"][-1]["configured"] is True
    request["model"] = "another-model"
    assert client.put("/models/catalog/remote-custom", json=request, headers=admin).status_code == 200
    assert model_spec("remote-custom").model == "another-model"
    selected = client.put(
        "/models/selection", json={"model_id": "remote-custom"}, headers=admin,
    )
    assert selected.status_code == 200
    assert selected.json()["default_id"] == "remote-custom"
    deleted = client.delete("/models/catalog/remote-custom", headers=admin)
    assert deleted.status_code == 200
    assert deleted.json()["default_id"] == "local-saluki"
    assert len(deleted.json()["models"]) == 3


@pytest.mark.parametrize(
    "endpoint", [
        "http://example.org/v1",
        "http://192.168.1.2:8000/v1",
        "http://169.254.169.254/latest",
        "https://user:password@example.org/v1",
        "https://example.org/v1?api_key=secret",
    ],
)
def test_insecure_endpoints_rejected(endpoint):
    request = custom_cloud()
    request["base_url"] = endpoint
    response = client.put(
        "/models/catalog/remote-custom", json=request,
        headers={"X-GeoFathom-Admin-Token": "test-admin-secret"},
    )
    assert response.status_code == 422


def test_local_endpoint_is_allowed_without_credentials():
    spec = ModelSpec(
        id="local-other", name="Local model", provider="ollama",
        model="local:latest", base_url="http://localhost:11434",
    )
    save_spec(spec)
    assert provider_for_spec(spec, Settings()) is not None


def test_preset_can_be_edited_but_not_deleted():
    admin = {"X-GeoFathom-Admin-Token": "test-admin-secret"}
    preset = model_spec("local-saluki").model_dump()
    preset["model"] = "my-real-ollama-tag"
    response = client.put("/models/catalog/local-saluki", json=preset, headers=admin)
    assert response.status_code == 200
    assert model_spec("local-saluki").model == "my-real-ollama-tag"
    assert client.delete("/models/catalog/local-saluki", headers=admin).status_code == 422


def test_no_arbitrary_environment_variable_access():
    request = custom_cloud()
    request["credential_env"] = "HOME"
    assert client.put(
        "/models/catalog/remote-custom", json=request,
        headers={"X-GeoFathom-Admin-Token": "test-admin-secret"},
    ).status_code == 422


def test_probe_specific_model_without_geocoder(monkeypatch):
    class Fake:
        async def parse(self, text):
            return {"action": "locate", "query": "Shanghai", "explanation": ""}

    monkeypatch.setattr(routes, "provider_for_spec", lambda spec, settings: Fake())
    response = client.post("/models/probe", json={"model_id": "local-saluki"})
    assert response.status_code == 200
    assert response.json()["model_id"] == "local-saluki"
    assert response.json()["live_call"] is True


def test_unknown_model_is_never_silently_substituted():
    assert client.post(
        "/assistant", json={"message": "Locate Hongqiao Airport", "model_id": "unknown"}
    ).status_code == 404


def test_secret_not_persisted_in_catalog(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_MODEL_KEY_CUSTOM", "mock-secret-that-must-not-appear")
    save_spec(ModelSpec(**custom_cloud()))
    stored = json.loads(
        __import__("pathlib").Path(__import__("os").environ["GEOFATHOM_MODEL_CATALOG_PATH"]).read_text()
    )
    assert "mock-secret-that-must-not-appear" not in json.dumps(stored)


def test_disabled_model_cannot_be_selected():
    spec = ModelSpec(
        id="disabled-example", name="Disabled", provider="ollama",
        model="test", base_url="http://127.0.0.1:11434", enabled=False,
    )
    save_spec(spec)
    with pytest.raises(CatalogError):
        select_default("disabled-example")


def test_browser_cors_allows_admin_configuration():
    response = client.options(
        "/models/catalog/custom-test",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "x-geofathom-admin-token,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PUT" in response.headers["access-control-allow-methods"]
