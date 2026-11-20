"""User-configurable local and cloud model directory.

The catalog persists model identifiers, endpoints and names, never API secrets.
Configuration mutations require an administrator token stored outside Git.
Only HTTPS remote endpoints and local-loopback HTTP endpoints are accepted.
"""

import hmac
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from core.config import Settings
from .llm import get_provider

_ROOT = Path(__file__).resolve().parent.parent
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_CREDENTIAL = re.compile(r"^GEOFATHOM_MODEL_KEY_[A-Z0-9_]{1,60}$")
_ALLOWED_KEYS = {
    "GEOFATHOM_GROQ_API_KEY", "GEOFATHOM_GEMINI_API_KEY",
    "GEOFATHOM_OPENAI_API_KEY",
}

_DEFAULT_MODELS = (
    {
        "id": "local-saluki", "name": "Saluki 27B (local)",
        "provider": "ollama", "model": "saluki",
        "base_url": "http://127.0.0.1:11434", "credential_env": "",
        "enabled": True,
    },
    {
        "id": "cloud-groq", "name": "GPT-OSS 120B (Groq)",
        "provider": "groq", "model": "openai/gpt-oss-120b",
        "base_url": "", "credential_env": "GEOFATHOM_GROQ_API_KEY",
        "enabled": True,
    },
    {
        "id": "cloud-gemini", "name": "Gemini 3.8 Flash (Google)",
        "provider": "gemini", "model": "gemini-3.8-flash",
        "base_url": "", "credential_env": "GEOFATHOM_GEMINI_API_KEY",
        "enabled": True,
    },
)
_DEFAULT_ID = "local-saluki"


class CatalogError(ValueError):
    """Invalid model configuration or unknown model."""


class ModelSpec(BaseModel):
    id: str = Field(min_length=2, max_length=63)
    name: str = Field(min_length=1, max_length=100)
    provider: str
    model: str = Field(min_length=1, max_length=180)
    base_url: str = Field(default="", max_length=500)
    credential_env: str = Field(default="", max_length=85)
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not _SLUG.fullmatch(value):
            raise ValueError("Model ID requires lowercase letters, digits, - or _.")
        return value

    @field_validator("provider")
    @classmethod
    def valid_provider(cls, value: str) -> str:
        if value not in {"ollama", "openai-compatible", "groq", "gemini"}:
            raise ValueError("Provider must be ollama, openai-compatible, groq, or gemini.")
        return value

    @field_validator("credential_env")
    @classmethod
    def valid_env(cls, value: str) -> str:
        if value and value not in _ALLOWED_KEYS and not _CREDENTIAL.fullmatch(value):
            raise ValueError("Use a GEOFATHOM_MODEL_KEY_* variable or an approved provider key.")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) base URL without credentials or query parameters.")
        host = parsed.hostname.lower()
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global and not ip.is_loopback:
                raise ValueError("Private, link-local and reserved IP endpoints are disallowed.")
        except ValueError as error:
            if "disallowed" in str(error):
                raise
        if parsed.scheme == "http" and not loopback:
            raise ValueError("Unencrypted HTTP is allowed only for loopback model servers.")
        return value.rstrip("/")


def validate_spec(spec: ModelSpec) -> None:
    if spec.provider in {"ollama", "openai-compatible"} and not spec.base_url:
        raise CatalogError("A local or OpenAI-compatible model requires a base URL.")
    if spec.provider in {"groq", "gemini"} and spec.base_url:
        raise CatalogError("Groq and Gemini use fixed official API endpoints.")


def catalog_path() -> Path:
    return Path(os.getenv("GEOFATHOM_MODEL_CATALOG_PATH") or
                _ROOT / "data" / "model-catalog.json")


def _load() -> dict:
    path = catalog_path()
    if not path.exists():
        return {"default_id": _DEFAULT_ID, "models": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not isinstance(loaded.get("models"), dict):
            raise CatalogError("Invalid model catalog format.")
        return loaded
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError("Model catalog could not be read.") from error


def _save(data: dict) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A secure temporary file avoids partial writes and keeps file permissions
    # restrictive on POSIX. No API key is written to this catalog.
    handle, temporary = tempfile.mkstemp(prefix=".models-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def list_specs() -> tuple[str, list[ModelSpec]]:
    saved = _load()
    merged = {item["id"]: item for item in _DEFAULT_MODELS}
    for identifier, item in saved["models"].items():
        spec = ModelSpec.model_validate(item)
        if identifier != spec.id:
            raise CatalogError("Catalog contains an inconsistent model identifier.")
        validate_spec(spec)
        merged[identifier] = spec.model_dump()
    models = [ModelSpec.model_validate(value) for value in merged.values()]
    if len(models) > 50:
        raise CatalogError("At most 50 model configurations are supported.")
    default_id = saved.get("default_id", _DEFAULT_ID)
    if default_id not in merged:
        default_id = _DEFAULT_ID
    return default_id, models


def model_spec(identifier: str) -> ModelSpec:
    for item in list_specs()[1]:
        if item.id == identifier:
            return item
    raise CatalogError("Model not found.")


def _secret(spec: ModelSpec, settings: Settings) -> str:
    if spec.credential_env == "GEOFATHOM_GROQ_API_KEY":
        return settings.groq_api_key
    if spec.credential_env == "GEOFATHOM_GEMINI_API_KEY":
        return settings.gemini_api_key
    if spec.credential_env == "GEOFATHOM_OPENAI_API_KEY":
        return settings.openai_api_key
    return os.getenv(spec.credential_env, "") if spec.credential_env else ""


def provider_for_spec(spec: ModelSpec, settings: Settings):
    if not spec.enabled:
        return None
    secret = _secret(spec, settings)
    if spec.provider in {"groq", "gemini"} and not secret:
        return None
    if spec.provider == "openai-compatible" and spec.credential_env and not secret:
        return None
    config = replace(
        settings,
        llm_provider=spec.provider,
        llm_model=spec.model,
        ollama_url=spec.base_url if spec.provider == "ollama" else settings.ollama_url,
        openai_base_url=(spec.base_url if spec.provider == "openai-compatible"
                         else settings.openai_base_url),
        openai_api_key=secret if spec.provider == "openai-compatible" else "",
        groq_api_key=secret if spec.provider == "groq" else settings.groq_api_key,
        gemini_api_key=secret if spec.provider == "gemini" else settings.gemini_api_key,
    )
    return get_provider(config)


def list_public(settings: Settings) -> dict:
    default_id, models = list_specs()
    return {
        "default_id": default_id,
        "models": [
            {
                **item.model_dump(),
                "preset": item.id in {entry["id"] for entry in _DEFAULT_MODELS},
                "configured": provider_for_spec(item, settings) is not None,
            }
            for item in models
        ],
        "note": "Credential values are never stored or returned. Add secrets to server environment.",
    }


def save_spec(spec: ModelSpec) -> None:
    validate_spec(spec)
    data = _load()
    _, models = list_specs()
    ids = {item.id for item in models}
    if len(ids) >= 50 and spec.id not in ids:
        raise CatalogError("Model limit reached.")
    data["models"][spec.id] = spec.model_dump()
    _save(data)


def remove_spec(identifier: str) -> None:
    data = _load()
    if identifier in {item["id"] for item in _DEFAULT_MODELS}:
        raise CatalogError("Preset models cannot be removed. Disable or customize them instead.")
    if identifier not in data["models"]:
        raise CatalogError("Model not found.")
    del data["models"][identifier]
    if data.get("default_id") == identifier:
        data["default_id"] = _DEFAULT_ID
    _save(data)


def select_default(identifier: str) -> None:
    spec = model_spec(identifier)
    if not spec.enabled:
        raise CatalogError("A disabled model cannot be the default.")
    data = _load()
    data["default_id"] = identifier
    _save(data)


def require_admin(value: str | None) -> None:
    expected = os.getenv("GEOFATHOM_MODEL_ADMIN_TOKEN", "")
    if not expected:
        raise PermissionError("Set GEOFATHOM_MODEL_ADMIN_TOKEN on the FastAPI server to edit models.")
    if not value or not hmac.compare_digest(value, expected):
        raise PermissionError("Invalid model configuration token.")
