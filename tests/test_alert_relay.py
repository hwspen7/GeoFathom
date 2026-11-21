import httpx
import pytest
from core.alerts import AlertRelay,check_metrics

def test_delivery_retry_restart_dedup_and_recovery(tmp_path):
    events=[]
    def handler(request):
        import json
        body=json.loads(request.content)
        events.append(body)
        assert request.headers["idempotency-key"]==body["event_id"]
        return httpx.Response(503 if len(events)==1 else 200)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path=tmp_path/"state.sqlite"
        relay=AlertRelay(path,"https://alerts.example.test/hook",client)
        assert relay.reconcile({"LOW_DISK"})==0
        relay=AlertRelay(path,"https://alerts.example.test/hook",client)
        assert relay.reconcile({"LOW_DISK"})==1
        assert events[0]==events[1]
        assert relay.reconcile({"LOW_DISK"})==0
        assert relay.reconcile(set())==1
        assert events[-1]["state"]=="resolved"
        assert events[-1]["event_id"]!=events[0]["event_id"]
        assert relay.reconcile(set())==0
        with pytest.raises(ValueError):
            relay.reconcile({"secret from untrusted server"})
        with pytest.raises(ValueError):
            AlertRelay(path,"http://alerts.example.test/hook",client)

def test_metrics_thresholds_and_unavailable_api():
    def handler(request):
        assert request.headers["X-GeoFathom-API-Key"]=="operator"
        return httpx.Response(200,json={"alerts":["LOW_DISK","private"],
            "requests":{"total":100,"server_errors":11},"rss_bytes":5000*1024**2})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check_metrics(client,"http://localhost:8000/health/metrics","operator")=={"LOW_DISK","HIGH_ERROR_RATE","HIGH_RSS"}
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(503))) as client:
        assert check_metrics(client,"http://localhost:8000/health/metrics","operator")=={"API_UNAVAILABLE"}

def test_outage_preserves_firing_then_recovery(tmp_path):
    seen=[];available=False
    def handler(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200 if available else 503)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        relay=AlertRelay(tmp_path/"state.sqlite","https://alerts.example.test/hook",client)
        relay.reconcile({"LOW_DISK"})
        relay.reconcile({"API_UNAVAILABLE"})
        available=True
        # The API recovered and confirmed disk recovery. Do not discard
        # the firing events that had not yet reached the receiver.
        assert relay.reconcile(set())==4
    assert [(v["code"],v["state"]) for v in seen[-4:]]==[
        ("LOW_DISK","firing"),("API_UNAVAILABLE","firing"),
        ("API_UNAVAILABLE","resolved"),("LOW_DISK","resolved")]
