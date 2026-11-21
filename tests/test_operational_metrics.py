from fastapi.testclient import TestClient
from core.main import app

def test_metrics_require_operator_and_do_not_leak_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOFATHOM_DATABASE_PATH",str(tmp_path/"metrics.sqlite"))
    monkeypatch.setenv("GEOFATHOM_AUTH_MODE","required")
    token="operator-"+"m"*40
    monkeypatch.setenv("GEOFATHOM_API_TOKEN",token)
    client=TestClient(app)
    assert client.get("/health/metrics").status_code==401
    assert client.get("/health").status_code==200
    response=client.get("/health/metrics",headers={"X-GeoFathom-API-Key":token})
    assert response.status_code==200,response.text
    state=response.json()
    assert state["rss_bytes"]>0
    assert state["requests"]["total"]>=2
    assert state["storage_free_bytes"]>0
    assert token not in response.text
    assert str(tmp_path) not in response.text
