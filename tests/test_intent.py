import pytest

from intelligence.intent import fallback_intent
from intelligence.llm import _decode


def test_chinese_area_request() -> None:
    result = fallback_intent("请帮我测量虹桥机场的占地面积")
    assert result["action"] == "locate"
    assert "虹桥机场" in result["query"]
    assert "面积" not in result["query"]


def test_spatial_filter_does_not_invent_results() -> None:
    assert fallback_intent("寻找面积超过20000平方米的建筑")["action"] == "discover"


def test_model_parser_rejects_invalid_actions() -> None:
    with pytest.raises(ValueError):
        _decode('{"action":"invent_coordinates","query":"airport"}')


def test_model_parser_accepts_structured_query() -> None:
    assert _decode('{"action":"locate","query":"Hongqiao Airport"}')["query"] == "Hongqiao Airport"

from core.config import Settings
from intelligence.llm import get_provider


def test_model_profiles_are_swappable():
    settings = Settings(
        llm_provider="ollama", llm_model="saluki",
        analysis_provider="openai-compatible",
        analysis_model="Qwen3.5-35B-A3B",
        analysis_base_url="http://localhost:8081/v1",
    )
    assert get_provider(settings).__class__.__name__ == "OllamaProvider"
    advanced = get_provider(settings, "analysis")
    assert advanced.__class__.__name__ == "OpenAICompatibleProvider"
    assert advanced.settings.llm_model == "Qwen3.5-35B-A3B"
    assert advanced.settings.openai_base_url == "http://localhost:8081/v1"


def test_advanced_profile_is_optional():
    assert get_provider(Settings(), "analysis") is None
