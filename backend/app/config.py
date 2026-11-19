"""Configurable infrastructure settings, independent of model implementation."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    contact_email: str = ""
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    llm_provider: str = "none"
    llm_model: str = ""
    ollama_url: str = "http://localhost:11434"
    openai_base_url: str = "http://localhost:8001/v1"
    openai_api_key: str = ""


def get_settings() -> Settings:
    origins = os.getenv("GEOFATHOM_CORS_ORIGINS", "http://localhost:5173")
    return Settings(
        contact_email=os.getenv("GEOFATHOM_CONTACT_EMAIL", ""),
        nominatim_url=os.getenv(
            "GEOFATHOM_NOMINATIM_URL", "https://nominatim.openstreetmap.org"
        ).rstrip("/"),
        overpass_url=os.getenv("GEOFATHOM_OVERPASS_URL", "https://overpass-api.de/api/interpreter").rstrip("/"),
        cors_origins=tuple(part.strip() for part in origins.split(",") if part.strip()),
        llm_provider=os.getenv("GEOFATHOM_LLM_PROVIDER", "none").lower(),
        llm_model=os.getenv("GEOFATHOM_LLM_MODEL", ""),
        ollama_url=os.getenv("GEOFATHOM_OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        openai_base_url=os.getenv(
            "GEOFATHOM_OPENAI_BASE_URL", "http://localhost:8001/v1"
        ).rstrip("/"),
        openai_api_key=os.getenv("GEOFATHOM_OPENAI_API_KEY", ""),
    )
