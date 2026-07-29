"""Research-only endpoints. EXPERIMENTAL/SHADOW — never a serving surface.

Serves the artifact an operator generated offline with
``pipeline.run_market_benchmark_report benchmark --output ...``. The endpoint
does no computation and reads no live table: research data is produced,
reviewed and versioned by a person, then served verbatim with its lineage,
exclusions and readiness states intact. If no artifact exists the endpoint
says so plainly instead of improvising one.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/research", tags=["research"])

#: Written only by the operator CLI; absent until someone runs it.
ARTIFACT_PATH = Path(__file__).resolve().parents[1] / "research_data" / (
    "market_benchmark.json")


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
    return {"experimental": True, "status": "ok", "artifact": artifact}
