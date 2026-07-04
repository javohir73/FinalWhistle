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
from datetime import date as date_type
from pathlib import Path

import requests
from sqlalchemy.orm import Session

from pipeline.team_mapping import normalize_team_name

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


def match_statsbomb_to_rows(
    sb_records: list[dict],
    historical_rows: list[dict],
    id_to_name: dict[int, "str | None"],
    normalize=lambda s: s,
) -> tuple[list[dict], list[dict]]:
    """Join StatsBomb match records onto `historical_matches` rows.

    Mirrors `ml/evaluation/market_benchmark.py::join_odds_to_rows`'s
    swap-and-flip precedent: `HistoricalMatch` has no home/away, only
    orientation-neutral `team_a`/`team_b`, so a swapped `(date, away, home)`
    key also matches — with `xg_a`/`xg_b` flipped onto `team_a`/`team_b`.

    `sb_records`: dicts with `match_date` (bare "YYYY-MM-DD"), `home_team`,
    `away_team`, `home_score`, `away_score`, `home_xg`, `away_xg`.
    `historical_rows`: dicts with `id`, `team_a_id`, `team_b_id`, `date`
    (a `date`/`datetime`), `score_a`, `score_b`, `xg_a`.

    Returns `(writes, unmatched)` where `writes` are `{"id", "xg_a", "xg_b"}`
    dicts ready to apply, and `unmatched` are the input rows (StatsBomb dicts)
    that didn't resolve to a write — no key hit, a score cross-check
    mismatch, or an ambiguous key collision. Never writes on ambiguity or a
    disagreeing score; both are logged and dropped rather than guessed.
    """
    by_key: dict[tuple, dict] = {}
    ambiguous: set[tuple] = set()
    for rec in sb_records:
        home = normalize(rec.get("home_team"))
        away = normalize(rec.get("away_team"))
        raw_date = rec.get("match_date")
        if not home or not away or not raw_date:
            continue
        # StatsBomb's match_date is a bare "YYYY-MM-DD"; historical_matches.date
        # is a midnight-UTC-pinned civil date (pipeline/ingest/historical_results.py:106)
        # -- compare as civil dates, no instant conversion.
        civil_date = (
            raw_date.date() if hasattr(raw_date, "date")
            else date_type.fromisoformat(raw_date)
        )
        key = (civil_date, home, away)
        if key in by_key:
            ambiguous.add(key)
            log.warning("statsbomb ambiguous fixture key collision: %s", key)
            continue
        by_key[key] = rec

    row_by_key: dict[tuple, dict] = {}
    for row in historical_rows:
        d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        name_a = normalize(id_to_name.get(row["team_a_id"]))
        name_b = normalize(id_to_name.get(row["team_b_id"]))
        if not name_a or not name_b:
            continue
        row_by_key[(d, name_a, name_b)] = row

    writes: list[dict] = []
    unmatched: list[dict] = []
    for key, rec in by_key.items():
        if key in ambiguous:
            unmatched.append(rec)
            continue

        civil_date, home, away = key
        row, swapped = row_by_key.get(key), False
        if row is None:
            row, swapped = row_by_key.get((civil_date, away, home)), True
        if row is None:
            unmatched.append(rec)
            continue

        home_score, away_score = rec.get("home_score"), rec.get("away_score")
        expected_a, expected_b = (
            (away_score, home_score) if swapped else (home_score, away_score)
        )
        if (
            expected_a is not None
            and expected_b is not None
            and (expected_a, expected_b) != (row["score_a"], row["score_b"])
        ):
            log.warning(
                "statsbomb score cross-check mismatch for row id=%s: "
                "statsbomb=%s/%s vs stored=%s/%s",
                row["id"], expected_a, expected_b, row["score_a"], row["score_b"],
            )
            unmatched.append(rec)
            continue

        home_xg, away_xg = rec.get("home_xg"), rec.get("away_xg")
        xg_a, xg_b = (away_xg, home_xg) if swapped else (home_xg, away_xg)
        writes.append({"id": row["id"], "xg_a": xg_a, "xg_b": xg_b})

    return writes, unmatched


def _resolvable_row_id(sb_match: dict, row_by_key: dict[tuple, dict], normalize) -> int | None:
    """Cheap key lookup only: does `sb_match` resolve (direct or swapped) to a
    row in `row_by_key`? Returns that row's id, or `None`. Used purely to
    decide whether a match's events are worth fetching at all -- it does NOT
    apply the score cross-check or ambiguity handling that the real
    `match_statsbomb_to_rows` pass performs once xG is known.
    """
    raw_date = sb_match.get("match_date")
    home = normalize(sb_match.get("home_team", {}).get("home_team_name"))
    away = normalize(sb_match.get("away_team", {}).get("away_team_name"))
    if not raw_date or not home or not away:
        return None
    d = date_type.fromisoformat(raw_date)
    row = row_by_key.get((d, home, away)) or row_by_key.get((d, away, home))
    return row["id"] if row is not None else None


def backfill_xg(
    db: Session,
    cache_dir: str | Path = "pipeline/data/statsbomb_cache",
    editions: list[tuple[int, int]] = SIX_EDITIONS,
) -> dict:
    """Populate `historical_matches.xg_a`/`xg_b` from StatsBomb open data.

    Best-effort and idempotent: never raises; rows whose `xg_a` is already
    non-NULL are skipped WITHOUT fetching their events (resume is free, even
    on a cold cache). Commits once per edition so interrupted runs lose at
    most one edition's work. Distinct log lines are emitted for an unmatched
    fixture (name gap), an xG-absent match, and an events-fetch failure.

    Returns a summary dict: `{editions, matches_seen, rows_written,
    skipped_populated, unmatched, xg_absent}`.
    """
    from app.models import HistoricalMatch, Team  # local import: keep this module DB-optional

    competitions_json = _get_json(f"{BASE_URL}/competitions.json")
    verified_editions = enumerate_editions(competitions_json) if competitions_json else []
    if not verified_editions:
        log.warning("statsbomb backfill: no editions verified against competitions.json; using pinned list")
        verified_editions = list(editions)

    id_to_name = {t.id: t.name for t in db.query(Team).all()}

    summary = {
        "editions": len(verified_editions),
        "matches_seen": 0,
        "rows_written": 0,
        "skipped_populated": 0,
        "unmatched": 0,
        "xg_absent": 0,
    }

    for cid, sid in verified_editions:
        sb_matches = _get_json(f"{BASE_URL}/matches/{cid}/{sid}.json") or []
        if not sb_matches:
            log.warning("statsbomb backfill: no matches for (competition_id=%s, season_id=%s)", cid, sid)
            continue
        summary["matches_seen"] += len(sb_matches)

        # In-scope national-team rows ONLY: date must fall within this
        # edition's actual match dates, so the swapped-key fallback in
        # match_statsbomb_to_rows can't accidentally match an unrelated
        # same-date friendly outside this edition.
        edition_dates = {
            date_type.fromisoformat(m["match_date"])
            for m in sb_matches
            if m.get("match_date")
        }
        orm_rows = [
            r for r in db.query(HistoricalMatch).filter(HistoricalMatch.date.isnot(None)).all()
            if (r.date.date() if hasattr(r.date, "date") else r.date) in edition_dates
        ]
        row_by_id = {r.id: r for r in orm_rows}

        # Idempotent skip: rows already populated are excluded from the join
        # dict entirely, so their events are never fetched.
        pending_rows = [r for r in orm_rows if r.xg_a is None]
        summary["skipped_populated"] += len(orm_rows) - len(pending_rows)

        row_dicts = [
            {"id": r.id, "team_a_id": r.team_a_id, "team_b_id": r.team_b_id,
             "date": r.date, "score_a": r.score_a, "score_b": r.score_b, "xg_a": r.xg_a}
            for r in pending_rows
        ]
        row_by_key: dict[tuple, dict] = {}
        for row in row_dicts:
            name_a = normalize_team_name(id_to_name.get(row["team_a_id"]))
            name_b = normalize_team_name(id_to_name.get(row["team_b_id"]))
            if name_a and name_b:
                row_by_key[(row["date"].date(), name_a, name_b)] = row

        # Build the in-scope join dict ONCE per edition, then only fetch
        # events for a match that resolves (direct or swapped) to a pending
        # row -- an already-populated row's events file is never touched.
        sb_records = []
        for m in sb_matches:
            row_id = _resolvable_row_id(m, row_by_key, normalize_team_name)
            home_xg = away_xg = None
            if row_id is not None:
                events = _fetch_events(m.get("match_id"), cache_dir)
                if not events:
                    log.warning("statsbomb backfill: events fetch failed for match_id=%s", m.get("match_id"))
                home_xg, away_xg = match_xg(m, events)
                if home_xg is None and away_xg is None:
                    summary["xg_absent"] += 1
                    log.warning(
                        "statsbomb backfill: no shot-xG for match_id=%s (%s vs %s)",
                        m.get("match_id"),
                        m.get("home_team", {}).get("home_team_name"),
                        m.get("away_team", {}).get("away_team_name"),
                    )
            sb_records.append({
                "match_date": m.get("match_date"),
                "home_team": m.get("home_team", {}).get("home_team_name"),
                "away_team": m.get("away_team", {}).get("away_team_name"),
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "home_xg": home_xg,
                "away_xg": away_xg,
            })

        writes, unmatched = match_statsbomb_to_rows(
            sb_records, row_dicts, id_to_name, normalize_team_name
        )

        for w in writes:
            row = row_by_id[w["id"]]
            row.xg_a = w["xg_a"]
            row.xg_b = w["xg_b"]
            summary["rows_written"] += 1

        for rec in unmatched:
            summary["unmatched"] += 1
            log.warning(
                "statsbomb backfill: unmatched fixture %s vs %s on %s",
                rec.get("home_team"), rec.get("away_team"), rec.get("match_date"),
            )

        db.commit()

    return summary
