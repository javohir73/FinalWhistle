"""StatsBomb open-data xG backfill for `historical_matches.xg_a`/`xg_b`.

Reproduces the shelved xG-team-offsets feature on a NEW data source: StatsBomb
open data (free, 314 international matches across 6 editions) instead of
API-Football (which has no WC2022 xG). Ships SHADOW-FIRST — this module only
populates `xg_a`/`xg_b`; nothing served changes and `params.team_offsets`
stays null.

Phase 2 (this file, first half): a pure, network-free shot-xG parser
(`sum_shot_xg_by_team`, `match_xg`) plus best-effort cached fetch helpers
(`_get_json`, `_fetch_events`). Phase 3 adds the swapped-orientation fixture
matcher and the idempotent `backfill_xg(db, ...)` orchestrator.

Never fabricates xG: an absent side, a fetch failure, or a malformed shot
event all resolve to `None` -> NULL, never `0.0`. The penalty shootout
(`period == 5`) is excluded — `historical_matches.score_a/score_b` is the
after-extra-time score (no shootout), so summing shootout shot-xG against it
would roughly double a knockout team's true attacking output. Grounded on the
WC2022 final (Argentina 3-3 France after ET): all-periods xG = 5.89/5.41 vs
periods-1-4 xG = 2.76/2.27.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# Pinned (competition_id, season_id) pairs for the 6 free editions with xG
# coverage (Phase 0, cleared). Copa America 2024's season_id (282) numerically
# collides with UEFA Euro 2024's, so editions are always keyed on the PAIR,
# never season_id alone.
SIX_EDITIONS: list[tuple[int, int]] = [
    (43, 3),      # FIFA World Cup 2018
    (43, 106),    # FIFA World Cup 2022
    (55, 43),     # UEFA Euro 2020
    (55, 282),    # UEFA Euro 2024
    (1267, 107),  # African Cup of Nations 2023
    (223, 282),   # Copa America 2024
]


def _get_json(url: str):
    """GET `url` and parse JSON; best-effort, never raises. `None` on failure."""
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as exc:  # noqa: BLE001 - fetch helper must never raise
        log.warning("statsbomb fetch failed: %s: %s", url, exc)
        return None


def enumerate_editions(competitions_json) -> list[tuple[int, int]]:
    """Filter-verify the pinned SIX_EDITIONS pairs against `competitions.json`.

    Guards against the ids silently drifting: only pairs that actually appear
    in the live competitions listing are returned, in SIX_EDITIONS order.
    """
    if not isinstance(competitions_json, list):
        return []
    live_pairs = {
        (c.get("competition_id"), c.get("season_id"))
        for c in competitions_json
        if isinstance(c, dict)
    }
    return [pair for pair in SIX_EDITIONS if pair in live_pairs]


def _fetch_events(match_id, cache_dir: str | Path) -> list[dict]:
    """Return the event list for `match_id`, cached on disk keyed by immutable id.

    Cache hit -> load from `cache_dir/events/{match_id}.json`. Cache miss ->
    GET from StatsBomb open-data and, on success, write the cache file before
    returning. Best-effort: any failure (network, bad JSON) yields `[]`, never
    raises. Cache is keyed by immutable StatsBomb match ids, so it never goes
    stale.
    """
    cache_path = Path(cache_dir) / "events" / f"{match_id}.json"
    if cache_path.exists():
        try:
            with cache_path.open() as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception as exc:  # noqa: BLE001 - corrupt cache file, refetch
            log.warning("statsbomb cache read failed: %s: %s", cache_path, exc)

    data = _get_json(f"{BASE_URL}/events/{match_id}.json")
    if not isinstance(data, list):
        return []

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w") as f:
            json.dump(data, f)
    except Exception as exc:  # noqa: BLE001 - cache write is best-effort
        log.warning("statsbomb cache write failed: %s: %s", cache_path, exc)

    return data


def sum_shot_xg_by_team(events: list[dict]) -> dict[str, float]:
    """Sum `shot.statsbomb_xg` per `team.name`, Shot events only, periods 1-4.

    Skips (never counts as 0.0): non-Shot events, the penalty shootout
    (`period == 5`), events missing a team name, and shots missing
    `statsbomb_xg`.
    """
    out: dict[str, float] = {}
    for e in events:
        if (e.get("type") or {}).get("name") == "Shot":
            if (e.get("period") or 0) > 4:  # exclude penalty shootout (period 5)
                continue
            team = (e.get("team") or {}).get("name")
            v = (e.get("shot") or {}).get("statsbomb_xg")
            if team is None or v is None:
                continue
            out[team] = out.get(team, 0.0) + float(v)
    return out


def match_xg(match: dict, events: list[dict]) -> tuple[float | None, float | None]:
    """Return `(home_xg, away_xg)` for `match`, or `None` for an absent side.

    Never fabricates: a side with zero shot-xG entries is `None`, not `0.0`.
    Malformed match/events input degrades to `(None, None)` rather than
    raising.
    """
    try:
        home_name = (match.get("home_team") or {}).get("home_team_name")
        away_name = (match.get("away_team") or {}).get("away_team_name")
        by_team = sum_shot_xg_by_team(
            [e for e in (events or []) if isinstance(e, dict)]
        )
    except Exception as exc:  # noqa: BLE001 - parser must never raise
        log.warning("match_xg failed on malformed input: %s", exc)
        return None, None
    return by_team.get(home_name), by_team.get(away_name)
