"""Explicit, small real-API benchmark for geographic intent parsing.

Use: python -m intelligence.benchmark --profile default --max-cases 6
This program consumes your provider's API quota. Never schedule it in CI.
The prompts are synthetic and contain no project data or credentials.
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from core.config import get_settings
from .llm import get_provider


@dataclass(frozen=True)
class Case:
    message: str
    action: Literal["locate", "discover"]
    expected_name: str = ""


CASES = (
    Case("Locate Shanghai Hongqiao International Airport.", "locate", "Hongqiao"),
    Case("请帮我测量青岛五四广场的占地面积", "locate", "五四"),
    Case("Find all buildings larger than 5,000 square meters in the current map view.", "discover"),
    Case("寻找这片地图上所有面积大于2公顷的水域", "discover"),
    Case("Find Beijing Capital International Airport's mapped boundary.", "locate", "Beijing"),
    Case("寻找距离道路500米以内的工业建筑", "discover"),
)


def _matches(case: Case, result: dict) -> bool:
    if result["action"] != case.action:
        return False
    if not case.expected_name:
        return bool(result["query"])
    return case.expected_name.casefold() in result["query"].casefold()


async def evaluate(profile: Literal["default", "analysis"], max_cases: int = 6) -> dict:
    """Run a fixed, non-private suite and return numeric correctness evidence."""
    if not 1 <= max_cases <= len(CASES):
        raise ValueError("max_cases must be between 1 and 6")
    settings = get_settings()
    provider = get_provider(settings, profile)
    if provider is None:
        return {
            "status": "not_configured",
            "profile": profile,
            "message": "Configure a provider and API key or local model before benchmarking.",
            "cases": [],
        }

    reports = []
    for case in CASES[:max_cases]:
        start = time.monotonic()
        try:
            parsed = await provider.parse(case.message)
            reports.append({
                "action": case.action,
                "passed": _matches(case, parsed),
                "actual_action": parsed["action"],
                "latency_ms": round((time.monotonic() - start) * 1000),
                "status": "ok",
            })
        except httpx.HTTPStatusError as error:
            reports.append({
                "action": case.action,
                "passed": False,
                "status": f"http_{error.response.status_code}",
                "latency_ms": round((time.monotonic() - start) * 1000),
            })
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            reports.append({
                "action": case.action,
                "passed": False,
                "status": "invalid_or_unavailable",
                "latency_ms": round((time.monotonic() - start) * 1000),
            })

    count = sum(item["passed"] for item in reports)
    return {
        "status": "complete",
        "profile": profile,
        "model": settings.llm_model if profile == "default" else settings.analysis_model,
        "cases": reports,
        "passed": count,
        "total": len(reports),
        "accuracy": count / len(reports),
        "limitations": "Intent parsing only; not a test of GIS accuracy or satellite image segmentation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate configured geospatial AI provider on synthetic prompts.")
    parser.add_argument("--profile", choices=("default", "analysis"), default="default")
    parser.add_argument("--max-cases", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(args.profile, args.max_cases)), indent=2))


if __name__ == "__main__":
    main()
