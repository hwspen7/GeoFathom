"""Interchangeable local and OpenAI-compatible intent providers."""

import json
from dataclasses import replace
from typing import Literal, Protocol

import httpx

from core.config import Settings

_SYSTEM = (
    "You are a geospatial intent parser. Respond ONLY with a JSON object with "
    "keys action, query, explanation. action is either locate or discover. "
    "For named place lookup, boundary lookup, or area measurement, use locate. "
    "The query must be only the geographic place name, with locality if supplied. "
    "For area filters, nearby feature search, or unnamed candidate discovery, "
    "use discover. Never fabricate coordinates, areas, geometries, or places."
)


class IntentProvider(Protocol):
    async def parse(self, message: str) -> dict: ...


class OllamaProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def parse(self, message: str) -> dict:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                f"{self.settings.ollama_url}/api/chat",
                json={
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": message},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                },
            )
            response.raise_for_status()
            return _decode(response.json()["message"]["content"])


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def parse(self, message: str) -> dict:
        headers = {}
        if self.settings.openai_api_key:
            headers["Authorization"] = f"Bearer {self.settings.openai_api_key}"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": message},
            ],
            "temperature": 0,
        }
        if self.settings.llm_provider == "groq":
            # Groq GPT-OSS supports JSON object mode and constrained output.
            payload["response_format"] = {"type": "json_object"}
            payload["max_completion_tokens"] = 1024
            payload["reasoning_effort"] = "low"
        async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
            response = await client.post(
                f"{self.settings.openai_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return _decode(response.json()["choices"][0]["message"]["content"])


def _decode(value: str) -> dict:
    text = value.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = text.split("\n", 1)[-1].rsplit(fence, 1)[0].strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("Model did not return an intent object.")
    action, query = result.get("action"), result.get("query")
    if action not in {"locate", "discover"} or not isinstance(query, str):
        raise ValueError("Model returned an unsupported action.")
    return {
        "action": action,
        "query": query.strip()[:200],
        "explanation": str(result.get("explanation", ""))[:300],
    }


def get_provider(settings: Settings, profile: Literal['default', 'analysis'] = 'default') -> IntentProvider | None:
    if profile == 'analysis':
        if not settings.analysis_model or settings.analysis_provider == 'none':
            return None
        settings = replace(
            settings,
            llm_provider=settings.analysis_provider,
            llm_model=settings.analysis_model,
            openai_base_url=settings.analysis_base_url,
            ollama_url=settings.analysis_ollama_url,
        )
    if not settings.llm_model:
        return None
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings)
    if settings.llm_provider == "openai-compatible":
        return OpenAICompatibleProvider(settings)
    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            return None
        return OpenAICompatibleProvider(replace(
            settings,
            openai_base_url="https://api.groq.com/openai/v1",
            openai_api_key=settings.groq_api_key,
        ))
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            return None
        return OpenAICompatibleProvider(replace(
            settings,
            openai_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            openai_api_key=settings.gemini_api_key,
        ))
    return None
