"""Benchmark semantics are unit-tested without consuming free API quota."""

import pytest

from intelligence import benchmark


@pytest.mark.asyncio
async def test_benchmark_uses_only_fixed_prompts(monkeypatch):
    observed = []

    class Provider:
        async def parse(self, message):
            observed.append(message)
            if "buildings" in message:
                return {"action": "discover", "query": message, "explanation": ""}
            return {"action": "locate", "query": "Shanghai Hongqiao Airport", "explanation": ""}

    monkeypatch.setattr(benchmark, "get_provider", lambda settings, profile: Provider())
    result = await benchmark.evaluate("default", max_cases=3)
    assert len(observed) == 3
    assert result["total"] == 3
    assert result["passed"] == 2
    assert result["cases"][2]["actual_action"] == "discover"


@pytest.mark.asyncio
async def test_missing_key_does_not_call_provider(monkeypatch):
    monkeypatch.setattr(benchmark, "get_provider", lambda settings, profile: None)
    result = await benchmark.evaluate("analysis", max_cases=2)
    assert result["status"] == "not_configured"
    assert result["cases"] == []


@pytest.mark.asyncio
async def test_benchmark_limits_are_enforced():
    with pytest.raises(ValueError):
        await benchmark.evaluate("default", max_cases=0)
    with pytest.raises(ValueError):
        await benchmark.evaluate("default", max_cases=999)
