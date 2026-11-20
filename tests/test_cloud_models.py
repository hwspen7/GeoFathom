"""Cloud API integrations are tested through a network-free HTTP transport."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from core.main import app
from intelligence.llm import get_provider
import intelligence.routes as intelligence_routes

client = TestClient(app)


@pytest.mark.parametrize("profile", ["default", "analysis"])
def test_missing_key_never_sends_cloud_request(profile, monkeypatch):
    monkeypatch.setattr(
        intelligence_routes, "settings",
        Settings(
            llm_provider="groq", llm_model="openai/gpt-oss-120b",
            analysis_provider="gemini", analysis_model="gemini-3.8-flash",
            groq_api_key="", gemini_api_key="",
        ),
    )
    assert client.post("/models/probe", json={"profile": profile}).status_code == 409
    assert client.get("/models").json()[profile]["configured"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile,expected_url,expected_model,expected_key",
    [
        ("default", "https://api.groq.com/openai/v1/chat/completions",
         "openai/gpt-oss-120b", "mock-groq-key"),
        ("analysis", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
         "gemini-3.8-flash", "mock-gemini-key"),
    ],
)
async def test_cloud_provider_request_contract(
    monkeypatch, profile, expected_url, expected_model, expected_key,
):
    original_client = httpx.AsyncClient
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(
            200, json={
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "action": "locate",
                            "query": "Shanghai Hongqiao International Airport",
                            "explanation": "Find mapped airport boundary",
                        })
                    }
                }]
            },
        )

    def client_factory(**kwargs):
        return original_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    settings = Settings(
        llm_provider="groq", llm_model="openai/gpt-oss-120b",
        analysis_provider="gemini", analysis_model="gemini-3.8-flash",
        groq_api_key="mock-groq-key", gemini_api_key="mock-gemini-key",
    )
    provider = get_provider(settings, profile)
    assert provider is not None
    parsed = await provider.parse("Locate Hongqiao Airport")
    assert parsed["action"] == "locate"
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == expected_url
    assert request.headers["Authorization"] == "Bearer " + expected_key
    payload = json.loads(request.content)
    assert payload["model"] == expected_model
    assert payload["messages"][-1]["role"] == "user"
    if profile == "default":
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["reasoning_effort"] == "low"
    else:
        assert "reasoning_effort" not in payload


def test_live_probe_calls_provider_but_not_gis(monkeypatch):
    calls = []

    class FakeProvider:
        async def parse(self, message):
            calls.append(message)
            return {"action": "locate", "query": "Hongqiao Airport", "explanation": ""}

    monkeypatch.setattr(intelligence_routes, "get_provider", lambda settings, profile: FakeProvider())
    result = client.post("/models/probe", json={"profile": "default"})
    assert result.status_code == 200
    assert result.json()["status"] == "ready"
    assert result.json()["live_call"] is True
    assert calls == ["Locate Shanghai Hongqiao International Airport."]


def test_rate_limited_probe_reports_quota(monkeypatch):
    class RateLimited:
        async def parse(self, message):
            response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
            raise httpx.HTTPStatusError(
                "rate limit", request=response.request, response=response,
            )

    monkeypatch.setattr(intelligence_routes, "get_provider", lambda settings, profile: RateLimited())
    result = client.post("/models/probe", json={"profile": "default"})
    assert result.status_code == 429
    assert "quota" in result.json()["detail"].lower()


def test_invalid_model_profile_rejected():
    result = client.post("/models/probe", json={"profile": "arbitrary-provider"})
    assert result.status_code == 422
