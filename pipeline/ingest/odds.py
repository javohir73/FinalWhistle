"""Pre-match bookmaker odds snapshot from API-Football (exact-score FR-4.1).

Fetches 1X2 ("Match Winner") and over/under-2.5 ("Goals Over/Under") prices
for scheduled matches inside a pre-kickoff window and stores ONE consensus
row per match per pass: the MEDIAN decimal price across bookmakers per
outcome, plus margin-free implied 1X2 probabilities and captured_at. The
rows feed the shadow model's market lambda-total anchor
(ml/models/odds_blend.py) — odds are a model input only, never shown to
users (PRD non-goal #8).

BEST-EFFORT BY CONTRACT (FR-4.2): any fetch failure, malformed answer or
empty market leaves the DB unchanged for that match and ``refresh_odds``
NEVER raises to callers — prediction generation must be unblockable by a
bookmaker feed being down. api-sports v3: GET /odds?fixture={id}, auth via
the `x-apisports-key` header (same as pipeline.ingest.api_football).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median

import requests
from sqlalchemy.orm import Session

from app.models import Match, Odds
from ml.models.odds_blend import remove_margin

log = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

#: api-sports bet names carrying the two markets the blend needs.
_BET_1X2 = "Match Winner"
_BET_OU = "Goals Over/Under"

#: Default pre-kickoff window: the daily pipeline plus the live path both run
#: well inside 48h of every fixture, so one snapshot per match is guaranteed.
WINDOW_HOURS = 48.0


def fetch_odds(api_key: str, fixture_id: int, timeout: float = 15.0) -> list[dict]:
    """Return the raw odds list for one fixture from api-sports.io."""
    resp = requests.get(
        f"{BASE_URL}/odds",
        headers={"x-apisports-key": api_key},
        params={"fixture": fixture_id},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        # api-sports answers 200 with an `errors` object on auth/quota/param issues.
        log.warning("api-football odds errors: %s", data["errors"])
    return data.get("response") or []


def _collect(entry: dict, prices: dict[str, list[float]]) -> None:
    """Pull this bookmaker's 1X2 and OU-2.5 prices into the accumulator."""
    wanted = {
        (_BET_1X2, "Home"): "home", (_BET_1X2, "Draw"): "draw", (_BET_1X2, "Away"): "away",
        (_BET_OU, "Over 2.5"): "over25", (_BET_OU, "Under 2.5"): "under25",
    }
    for bet in entry.get("bets") or []:
        if not isinstance(bet, dict):
            continue
        for value in bet.get("values") or []:
            if not isinstance(value, dict):
                continue
            key = wanted.get((bet.get("name"), value.get("value")))
            if key is None:
                continue
            try:
                odd = float(value.get("odd"))
            except (TypeError, ValueError):
                continue
            if odd > 0:
                prices[key].append(odd)


def median_prices(response: list[dict]) -> dict | None:
    """PURE consensus: api-sports /odds response -> median decimal price per
    outcome across all bookmakers. Returns None when no bookmaker carries a
    complete market; per-key values are None when only that market is absent.
    """
    prices: dict[str, list[float]] = {k: [] for k in ("home", "draw", "away", "over25", "under25")}
    for item in response or []:
        if not isinstance(item, dict):
            continue
        for entry in item.get("bookmakers") or []:
            if isinstance(entry, dict):
                _collect(entry, prices)

    med = {k: (median(v) if v else None) for k, v in prices.items()}
    has_1x2 = all(med[k] is not None for k in ("home", "draw", "away"))
    has_ou = med["over25"] is not None and med["under25"] is not None
    if not has_1x2 and not has_ou:
        return None
    if not has_1x2:  # never store a partial triple — margin removal needs all three
        med["home"] = med["draw"] = med["away"] = None
    if not has_ou:
        med["over25"] = med["under25"] = None
    return med


def _fixture_id(db: Session, match: Match, api_key: str) -> int | None:
    """Provider fixture id: the stored one, else the lineups path's cached
    resolver (team pair + kickoff date). Indirection point for tests."""
    if match.provider_fixture_id is not None:
        return match.provider_fixture_id
    from app.lineups import _resolve_fixture_id

    return _resolve_fixture_id(db, match, api_key)


def refresh_odds(db: Session, api_key: str, window_hours: float = WINDOW_HOURS) -> dict:
    """One best-effort odds pass over upcoming matches. NEVER raises (FR-4.2).

    For every scheduled match with both teams known kicking off inside
    ``window_hours``, fetch the fixture's odds and append one median consensus
    row. A match that cannot be priced (no fixture id, feed down, no markets)
    is skipped silently — the shadow blend then falls back to pure Elo lambdas
    for it, which is the designed degradation.
    """
    now = datetime.now(timezone.utc)
    summary = {"matches_priced": 0, "matches_skipped": 0}
    try:
        matches = (
            db.query(Match)
            .filter(
                Match.status == "scheduled",
                Match.team_home_id.isnot(None),
                Match.team_away_id.isnot(None),
                Match.kickoff_utc.isnot(None),
                Match.kickoff_utc >= now,
                Match.kickoff_utc <= now + timedelta(hours=window_hours),
            )
            .order_by(Match.kickoff_utc.asc(), Match.id.asc())
            .all()
        )
        for m in matches:
            try:
                fid = _fixture_id(db, m, api_key)
                if fid is None:
                    summary["matches_skipped"] += 1
                    continue
                med = median_prices(fetch_odds(api_key, fid))
            except Exception as exc:  # noqa: BLE001 - best-effort per match
                log.warning("odds fetch failed for match %s: %s", m.id, exc)
                summary["matches_skipped"] += 1
                continue
            if med is None:
                summary["matches_skipped"] += 1
                continue
            implied = (None, None, None)
            if med["home"] is not None:
                implied = remove_margin((med["home"], med["draw"], med["away"]))
            db.add(
                Odds(
                    match_id=m.id,
                    bookmaker="median",
                    odds_home=med["home"],
                    odds_draw=med["draw"],
                    odds_away=med["away"],
                    odds_over25=med["over25"],
                    odds_under25=med["under25"],
                    implied_prob_home=implied[0],
                    implied_prob_draw=implied[1],
                    implied_prob_away=implied[2],
                    captured_at=now,
                )
            )
            summary["matches_priced"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the pass itself must never raise
        db.rollback()
        log.warning("odds refresh aborted: %s", exc)
        return {"matches_priced": 0, "matches_skipped": summary["matches_skipped"],
                "error": str(exc)}
    return summary
