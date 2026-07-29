"""Research-only endpoints. EXPERIMENTAL/SHADOW — never a serving surface.

Serves the artifact an operator generated offline with
``pipeline.run_market_benchmark_report benchmark --output ...``. The endpoint
does no computation and reads no live table.

DELIBERATELY PUBLIC — and enforced, not asserted. The response is
RECONSTRUCTED through a strict allowlist: every field the page renders is
validated for type and domain (finite numbers, parseable aware timestamps,
enum statuses), and anything not on the allowlist simply does not exist in
the response. A field that never leaves this function cannot leak, whatever
an artifact file happens to contain; and a value that fails its domain check
turns the whole response into ``invalid`` with the reason, never a page
crash. `noindex` on the page is politeness; this allowlist is the boundary.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/research", tags=["research"])

#: Written only by the operator CLI; absent until someone runs it.
ARTIFACT_PATH = Path(__file__).resolve().parents[1] / "research_data" / (
    "market_benchmark.json")

#: The artifact version this API knows how to serve. An artifact from a
#: different generator version is refused, not improvised around.
EXPECTED_ARTIFACT_VERSION = "market-benchmark-artifact-v1"

_STATUSES = {"READY", "NOT_READY"}
_VERDICTS = {"model_beats_venue", "venue_beats_model", "inconclusive"}


class _Invalid(ValueError):
    """One precise reason the artifact cannot be served."""


def _string(value, where, *, max_length=500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Invalid(f"{where} must be a non-empty string")
    return value[:max_length]


def _timestamp(value, where) -> str:
    text = _string(value, where)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _Invalid(f"{where} is not an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise _Invalid(f"{where} must be timezone-aware")
    return text


def _number(value, where, *, minimum=None, maximum=None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Invalid(f"{where} must be a number")
    if not math.isfinite(value):
        raise _Invalid(f"{where} must be finite")
    if minimum is not None and value < minimum:
        raise _Invalid(f"{where} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise _Invalid(f"{where} must be <= {maximum}")
    return value


def _count(value, where) -> int:
    number = _number(value, where, minimum=0)
    if int(number) != number:
        raise _Invalid(f"{where} must be an integer")
    return int(number)


def _count_map(value, where) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _Invalid(f"{where} must be an object")
    return {
        _string(key, f"{where} key"): _count(item, f"{where}[{key}]")
        for key, item in sorted(value.items())
    }


def _metrics(value, where) -> dict:
    if not isinstance(value, dict):
        raise _Invalid(f"{where} must be an object")
    return {
        "log_loss": _number(value.get("log_loss"), f"{where}.log_loss", minimum=0),
        "brier": _number(value.get("brier"), f"{where}.brier", minimum=0, maximum=2),
        "n": _count(value.get("n"), f"{where}.n"),
    }


def _group(value, index) -> dict:
    where = f"benchmark.groups[{index}]"
    if not isinstance(value, dict):
        raise _Invalid(f"{where} must be an object")
    status = value.get("status")
    if status not in _STATUSES:
        raise _Invalid(f"{where}.status {status!r} is not READY/NOT_READY")
    group = {
        "venue": _string(value.get("venue"), f"{where}.venue", max_length=60),
        "status": status,
        "n_matches": _count(value.get("n_matches"), f"{where}.n_matches"),
        "min_matches": _count(value.get("min_matches"), f"{where}.min_matches"),
    }
    if status == "NOT_READY":
        if value.get("reason") is not None:
            group["reason"] = _string(value.get("reason"), f"{where}.reason")
        return group
    window = value.get("capture_window")
    if isinstance(window, dict):
        group["capture_window"] = {
            "first_kickoff": _timestamp(window.get("first_kickoff"),
                                        f"{where}.capture_window.first_kickoff"),
            "last_kickoff": _timestamp(window.get("last_kickoff"),
                                       f"{where}.capture_window.last_kickoff"),
        }
    for series in ("model", "venue_normalized", "baseline_uniform"):
        group[series] = _metrics(value.get(series), f"{where}.{series}")
    group["delta_log_loss_model_minus_venue"] = _number(
        value.get("delta_log_loss_model_minus_venue"), f"{where}.delta")
    ci = value.get("delta_ci95_match_clustered")
    if ci is not None:
        if not isinstance(ci, (list, tuple)) or len(ci) != 2:
            raise _Invalid(f"{where}.delta_ci95 must be a [low, high] pair")
        low = _number(ci[0], f"{where}.delta_ci95[0]")
        high = _number(ci[1], f"{where}.delta_ci95[1]")
        if low > high:
            raise _Invalid(f"{where}.delta_ci95 is inverted")
        group["delta_ci95_match_clustered"] = [low, high]
    else:
        group["delta_ci95_match_clustered"] = None
    verdict = value.get("verdict")
    if verdict not in _VERDICTS:
        raise _Invalid(f"{where}.verdict {verdict!r} is not a known verdict")
    group["verdict"] = verdict
    return group


def _health_venue(value, venue) -> dict:
    where = f"health.venues[{venue}]"
    if not isinstance(value, dict):
        raise _Invalid(f"{where} must be an object")
    freshness_raw = value.get("quote_freshness_by_transport")
    freshness = {}
    if freshness_raw is not None:
        if not isinstance(freshness_raw, dict):
            raise _Invalid(f"{where}.quote_freshness_by_transport must be an object")
        for transport, item in sorted(freshness_raw.items()):
            if not isinstance(item, dict):
                raise _Invalid(f"{where} freshness[{transport}] must be an object")
            freshness[_string(transport, f"{where} transport", max_length=20)] = {
                "latest_quote_at": _timestamp(
                    item.get("latest_quote_at"),
                    f"{where} freshness[{transport}].latest_quote_at"),
                "age_seconds": _count(
                    item.get("age_seconds"),
                    f"{where} freshness[{transport}].age_seconds"),
            }
    incomplete = value.get("fixtures_incomplete_1x2", [])
    missing = value.get("fixtures_missing_prematch_quote", [])
    silent = value.get("markets_without_any_quote", [])
    for name, item in (("fixtures_incomplete_1x2", incomplete),
                       ("fixtures_missing_prematch_quote", missing),
                       ("markets_without_any_quote", silent)):
        if not isinstance(item, list):
            raise _Invalid(f"{where}.{name} must be a list")
    return {
        "markets_total": _count(value.get("markets_total"),
                                f"{where}.markets_total"),
        "mapping": _count_map(value.get("mapping"), f"{where}.mapping"),
        "mapped_fixtures": _count(value.get("mapped_fixtures"),
                                  f"{where}.mapped_fixtures"),
        "fixtures_with_complete_1x2": _count(
            value.get("fixtures_with_complete_1x2"),
            f"{where}.fixtures_with_complete_1x2"),
        "fixtures_incomplete_1x2": [
            _count(item, f"{where}.fixtures_incomplete_1x2[]")
            for item in incomplete],
        "fixtures_missing_prematch_quote": [
            _count(item, f"{where}.fixtures_missing_prematch_quote[]")
            for item in missing],
        "markets_without_any_quote": [
            _string(item, f"{where}.markets_without_any_quote[]",
                    max_length=255)
            for item in silent],
        "quote_freshness_by_transport": freshness,
    }


def sanitize_artifact(artifact: object) -> dict:
    """Reconstruct the render-safe, public-allowlisted response.

    Raises :class:`_Invalid` on any type or domain violation. Fields not
    reconstructed here are dropped by construction -- the allowlist IS the
    public-data boundary.
    """
    if not isinstance(artifact, dict):
        raise _Invalid("artifact is not an object")
    if artifact.get("artifact_version") != EXPECTED_ARTIFACT_VERSION:
        raise _Invalid(
            f"artifact_version {artifact.get('artifact_version')!r} is not "
            f"{EXPECTED_ARTIFACT_VERSION!r}")
    if artifact.get("experimental") is not True:
        raise _Invalid("artifact is not marked experimental")
    benchmark = artifact.get("benchmark")
    if not isinstance(benchmark, dict) or not isinstance(
            benchmark.get("groups"), list):
        raise _Invalid("artifact has no benchmark.groups list")
    split_raw = benchmark.get("split")
    split = None
    if isinstance(split_raw, dict):
        split = {
            "train_matches": _count(split_raw.get("train_matches"),
                                    "benchmark.split.train_matches"),
            "holdout_matches": _count(split_raw.get("holdout_matches"),
                                      "benchmark.split.holdout_matches"),
        }
    health_raw = artifact.get("health")
    if not isinstance(health_raw, dict):
        raise _Invalid("artifact has no health object")
    venues_raw = health_raw.get("venues", {})
    if not isinstance(venues_raw, dict):
        raise _Invalid("health.venues must be an object")
    heartbeat_raw = health_raw.get("heartbeat_freshness_by_venue_worker", {})
    if not isinstance(heartbeat_raw, dict):
        raise _Invalid(
            "health.heartbeat_freshness_by_venue_worker must be an object")
    heartbeat = {}
    for key, item in sorted(heartbeat_raw.items()):
        if not isinstance(item, dict):
            raise _Invalid(f"heartbeat[{key}] must be an object")
        heartbeat[_string(key, "heartbeat key", max_length=200)] = {
            "last_completed_at": _timestamp(
                item.get("last_completed_at"),
                f"heartbeat[{key}].last_completed_at"),
            "age_seconds": _count(item.get("age_seconds"),
                                  f"heartbeat[{key}].age_seconds"),
        }
    return {
        "artifact_version": EXPECTED_ARTIFACT_VERSION,
        "experimental": True,
        "generated_at": _timestamp(artifact.get("generated_at"), "generated_at"),
        "coverage": _count_map(artifact.get("coverage"), "coverage"),
        "exclusions": _count_map(artifact.get("exclusions"), "exclusions"),
        "benchmark": {
            "groups": [
                _group(group, index)
                for index, group in enumerate(benchmark["groups"])
            ],
            "split": split,
        },
        "health": {
            "venues": {
                _string(venue, "health venue", max_length=60):
                    _health_venue(item, venue)
                for venue, item in sorted(venues_raw.items())
            },
            "heartbeat_freshness_by_venue_worker": heartbeat,
        },
    }


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
    try:
        sanitized = sanitize_artifact(artifact)
    except _Invalid as exc:
        return {
            "experimental": True,
            "status": "invalid",
            "detail": str(exc),
        }
    return {"experimental": True, "status": "ok", "artifact": sanitized}
