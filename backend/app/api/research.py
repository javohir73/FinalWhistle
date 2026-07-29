"""Research-only endpoints. EXPERIMENTAL/SHADOW — never a serving surface.

Serves the artifact an operator generated offline with
``pipeline.run_market_benchmark_report benchmark --output ...``. The endpoint
does no computation and reads no live table: research data is produced,
reviewed and versioned by a person, then served verbatim with its lineage,
exclusions and readiness states intact.

DELIBERATELY PUBLIC. The artifact contains only aggregate research metrics,
counts, venue market tickers (public identifiers) and timestamps -- no user
data, no credentials, no non-public model internals. `noindex` on the page is
politeness, not protection; publishability is guaranteed by what the artifact
is allowed to contain, which the schema check below enforces in shape.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/research", tags=["research"])

#: Written only by the operator CLI; absent until someone runs it.
ARTIFACT_PATH = Path(__file__).resolve().parents[1] / "research_data" / (
    "market_benchmark.json")

#: The artifact version this API knows how to serve. An artifact from a
#: different generator version is refused, not improvised around.
EXPECTED_ARTIFACT_VERSION = "market-benchmark-artifact-v1"


def _validate(artifact: object) -> str | None:
    """Why this artifact must not be served, or None."""
    if not isinstance(artifact, dict):
        return "artifact is not an object"
    if artifact.get("artifact_version") != EXPECTED_ARTIFACT_VERSION:
        return (
            f"artifact_version {artifact.get('artifact_version')!r} is not "
            f"{EXPECTED_ARTIFACT_VERSION!r}"
        )
    if artifact.get("experimental") is not True:
        return "artifact is not marked experimental"
    if not isinstance(artifact.get("generated_at"), str):
        return "artifact has no generated_at"
    benchmark = artifact.get("benchmark")
    if not isinstance(benchmark, dict) or not isinstance(
            benchmark.get("groups"), list):
        return "artifact has no benchmark.groups list"
    for key in ("coverage", "exclusions", "health"):
        if not isinstance(artifact.get(key), dict):
            return f"artifact has no {key} object"
    return None


@router.get("/market-benchmark")
def market_benchmark() -> dict:
    """The shadow venue-benchmark artifact, or an honest empty state."""
    if not ARTIFACT_PATH.exists():
        return {
            "experimental": True,
            "status": "no_data",
            "detail": (
                "no benchmark artifact has been generated; run "
                "pipeline.run_market_benchmark_report with --output to "
                "produce one"
            ),
        }
    try:
        artifact = json.loads(ARTIFACT_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {
            "experimental": True,
            "status": "unreadable",
            "detail": "the benchmark artifact exists but cannot be parsed",
        }
    problem = _validate(artifact)
    if problem is not None:
        # Valid JSON is not a valid artifact: {} parsed fine and would have
        # crashed the page. Shape is checked here, where the honest answer
        # ("invalid, and here is why") is still possible.
        return {
            "experimental": True,
            "status": "invalid",
            "detail": problem,
        }
    return {"experimental": True, "status": "ok", "artifact": artifact}
