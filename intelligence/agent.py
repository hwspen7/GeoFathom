"""Bounded AI-to-tool execution for geographic and area-based queries.

Models select an intent, but never supply measurements or trusted coordinates.
The only search area comes from a user's current viewport. Every tool outcome
preserves data provenance and can return an explicit unable-to-execute status.
"""

import logging
import re
from typing import Any, Literal

import httpx

from core.config import Settings
from geometry.measure import GeometryError, measure_geometry
from places.discovery import DiscoveryError, discover_features
from places.geocoding import search_places
from .intent import fallback_intent
from .llm import get_provider
from .catalog import model_spec, provider_for_spec

logger = logging.getLogger("geofathom.agent")

_FEATURE_CLASSES = {
    "building": ("建筑", "楼", "building", "roof", "warehouse", "厂房"),
    "water": ("水域", "湖", "池塘", "water", "lake", "pond"),
    "landuse": ("地块", "绿地", "土地", "区域", "land", "parcel", "field", "park"),
}
_UNIT_FACTORS = {
    "平方米": 1, "平米": 1, "m²": 1, "m2": 1, "square meters": 1,
    "公顷": 10_000, "ha": 10_000,
    "平方公里": 1_000_000, "km²": 1_000_000, "km2": 1_000_000,
}
_UNIT = r"(平方米|平方公里|平米|公顷|m²|m2|km²|km2|ha|square meters)"
_VALUE = r"([0-9]+(?:\.[0-9]+)?)"


def _category(message: str) -> str:
    lower = message.casefold()
    for category, words in _FEATURE_CLASSES.items():
        if any(word.casefold() in lower for word in words):
            return category
    return "building"


def _area_filters(message: str) -> tuple[float, float | None]:
    """Only parse explicit area thresholds, never a distance-radius constraint."""
    lower = message.casefold()
    minimum = 0.0
    maximum = None
    expression = rf"(超过|大于|至少|不少于|小于|低于|最多|不超过|over|under|at least|at most|larger than|smaller than)\s*{_VALUE}\s*{_UNIT}"
    for match in re.finditer(expression, lower, flags=re.IGNORECASE):
        operator, value, unit = match.groups()
        area = float(value) * _UNIT_FACTORS[unit]
        if operator in {"超过", "大于", "至少", "不少于", "over", "at least", "larger than"}:
            minimum = max(minimum, area)
        else:
            maximum = min(maximum, area) if maximum is not None else area
    return minimum, maximum


def _unsupported_filter(message: str) -> bool:
    """Require an indexed road/distance dataset for proximity predicates."""
    return bool(re.search(
        r"(?:公里以内|米以内|距离.{0,20}(?:米|公里)|within\s+\d+(?:\s*)(?:km|meters?|m)\b|附近|nearby)",
        message, re.IGNORECASE,
    ))


def _trace(tool: str, status: str, details: str) -> dict:
    return {"tool": tool, "status": status, "details": details}


async def execute(
    message: str, settings: Settings,
    bbox: tuple[float, float, float, float] | None = None,
    profile: Literal["default", "analysis"] = "default",
    model_id: str | None = None,
) -> dict[str, Any]:
    """Execute a small, auditable set of verified geographic operations."""
    intent = fallback_intent(message)
    model_used = False
    steps = []
    provider = (
        provider_for_spec(model_spec(model_id), settings)
        if model_id else get_provider(settings, profile)
    )
    if (model_id is not None or profile == "analysis") and provider is None:
        return {
            "intent": intent, "model_used": False, "results": [],
            "measurement": None, "steps": [],
            "status": "not_supported",
            "message": "The selected model is not configured. Check its API key, endpoint or enabled status.",
        }
    if provider:
        try:
            parsed = await provider.parse(message)
            if parsed["query"]:
                intent = parsed
                model_used = True
                steps.append(_trace("model_intent", "ok", model_id or profile))
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
            logger.warning("Model unavailable; using deterministic parser: %s", error)
            steps.append(_trace("model_intent", "fallback", "Deterministic interpretation"))

    base = {
        "intent": intent,
        "model_used": model_used,
        "results": [],
        "measurement": None,
        "steps": steps,
    }

    if intent["action"] == "discover":
        if bbox is None:
            return {
                **base, "status": "not_supported",
                "message": "Choose and zoom into a map area before requesting area-based search.",
            }
        if _unsupported_filter(message):
            return {
                **base, "status": "not_supported",
                "message": "Road-distance or proximity constraints require a spatial network index.",
            }
        minimum, maximum = _area_filters(message)
        if maximum is not None and maximum < minimum:
            return {**base, "status": "invalid_filter", "message": "Area limits conflict."}
        try:
            data = await discover_features(bbox, _category(message), minimum, maximum, settings)
        except DiscoveryError:
            return {
                **base, "status": "needs_viewport",
                "message": "Zoom into a neighborhood-scale map view, then retry the area search.",
            }
        steps.append(_trace("discover_features", "ok", data["source"]))
        results = data["results"]
        return {
            **base,
            "status": "matched" if results else "not_found",
            "message": (
                f"Found {len(results)} mapped area candidates. " if results
                else "No mapped candidates matched. "
            ) + data["warning"],
            "results": results,
            "measurement": results[0]["measurement"] if results else None,
            "truncated": data["truncated"],
        }

    query = intent["query"].strip()
    if len(query) < 2:
        return {**base, "status": "invalid_query", "message": "Specify a place name."}
    candidates = await search_places(query, settings)
    steps.append(_trace("search_places", "ok", "OpenStreetMap via Nominatim"))
    if not candidates:
        return {
            **base, "status": "not_found",
            "message": "No reliable place match. Try a different name or draw on the map.",
        }
    boundary = candidates[0].get("geometry")
    measurement = None
    if boundary:
        try:
            measurement = measure_geometry(boundary)
            steps.append(_trace("measure_geometry", "ok", "WGS84 geodesic"))
        except GeometryError:
            boundary = None
            steps.append(_trace("measure_geometry", "unavailable", "Invalid mapped geometry"))
    message_out = (
        "Found mapped geometry. Check that it represents your intended boundary."
        if boundary else
        "Location found without a usable mapped boundary. Draw a polygon to measure."
    )
    return {
        **base,
        "status": "matched" if len(candidates) == 1 else "candidates",
        "message": message_out,
        "results": candidates,
        "measurement": measurement,
    }
