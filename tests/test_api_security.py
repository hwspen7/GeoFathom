"""Host-only and opt-in authenticated API protection regressions."""
import pytest
from fastapi.testclient import TestClient
from core.main import app
from core.security import _loopback

client=TestClient(app)


def test_loopback_only_host_policy():
    assert _loopback("testclient")
    assert _loopback("localhost")
    assert _loopback("127.0.0.1")
    assert _loopback("::1")
    assert not _loopback("8.8.8.8")
    assert not _loopback("example.com")


def test_required_mode_rejects_unauthenticated_requests(monkeypatch,tmp_path):
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","required")
    token="operator-access-key-"+"n"*40
    monkeypatch.setenv("GEOFATHOM_API_TOKEN",token)
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"secured.sqlite"))
    assert client.get("/health").status_code==200
    no=client.get("/projects")
    assert no.status_code==401
    assert no.headers["cache-control"]=="no-store"
    assert no.headers["www-authenticate"]=="Bearer"
    assert "X-Request-ID" in no.headers
    assert "X-Process-Time-ms" in no.headers
    wrong=client.post("/projects",json={"name":"Unapproved"})
    assert wrong.status_code==401
    correct=client.post("/projects",json={"name":"Approved"},
        headers={"X-GeoFathom-API-Key":token})
    assert correct.status_code==201,correct.text
    bearer=client.get("/projects",headers={
        "Authorization":"Bearer "+token})
    assert bearer.status_code==200
    assert bearer.json()["total"]==1


def test_auth_mode_requires_a_strong_configured_secret(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","required")
    monkeypatch.setenv("GEOFATHOM_API_TOKEN","short")
    assert client.get("/projects").status_code==503
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","unsupported")
    assert client.get("/projects").status_code==503


def test_browser_preflight_is_permitted_without_credentials(monkeypatch):
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","required")
    monkeypatch.setenv("GEOFATHOM_API_TOKEN","s"*40)
    resp=client.options("/projects",headers={
        "Origin":"http://localhost:5173",
        "Access-Control-Request-Method":"GET",
        "Access-Control-Request-Headers":"X-GeoFathom-API-Key",
    })
    assert resp.status_code==200
    assert resp.headers["access-control-allow-origin"]=="http://localhost:5173"
