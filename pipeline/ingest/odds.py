"""Pre-match bookmaker odds snapshot from API-Football (exact-score FR-4.1).

Fetches 1X2 ("Match Winner") and over/under-2.5 ("Goals Over/Under") prices
for scheduled matches inside a pre-kickoff window and stores ONE consensus
row per match per pass: the MEDIAN decimal price across bookmakers per
outcome, plus margin-free implied 1X2 probabilities and captured_at. The
rows feed the shadow model's market lambda-total anchor
(ml/models/odds_blend.py) — odds are a model input only, never shown to
users (PRD non-goal #8).

``refresh_odds`` is the daily one-row-per-match pass. ``snapshot_phased_odds``
is the hourly sibling that instead tags rows with a pre-kickoff band
(opening/t24/t6/t1/closing, pipeline.ingest.odds_phases) so a match can carry
a phased closing-line archive of up to five rows.

BEST-EFFORT BY CONTRACT (FR-4.2): any fetch failure, malformed answer or
empty market leaves the DB unchanged for that match and neither pass ever
raises to callers — prediction generation must be unblockable by a
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
from pipeline.ingest.odds_phases import due_phase

log = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

#: api-sports bet names carrying the two markets the blend needs.
_BET_1X2 = "Match Winner"
_BET_OU = "Goals Over/Under"

#: Default pre-kickoff window: the daily pipeline plus the live path both run
#: well inside 48h of every fixture, so one snapshot per match is guaranteed.
WINDOW_HOURS = 48.0

#: Post-match backfill horizon: api-sports keeps a fixture's frozen pre-match
#: odds ~7 days after full time, so an outage-missed match is recoverable
#: inside this window.
BACKFILL_DAYS = 7.0

#: Per-pass fetch cap for the hourly phased snapshot (api-sports free tier is
#: ~100 req/day; 40 leaves headroom for the daily refresh + live/lineups paths).
MAX_FETCHES_PER_PASS = 40


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


def _snapshot_match(db: Session, m: Match, api_key: str, now: datetime,
                    phase: str | None = None) -> bool:
    """Fetch and stage one median consensus row for ``m``, tagged with
    ``phase`` (default None — the legacy single-snapshot behavior used by
    refresh_odds/backfill_finished_odds, unchanged). True when a row was
    added to the session; False on any per-match miss (no fixture id, feed
    down, no markets) — logged, never raised, commit stays with the caller."""
    try:
        fid = _fixture_id(db, m, api_key)
        if fid is None:
            return False
        med = median_prices(fetch_odds(api_key, fid))
    except Exception as exc:  # noqa: BLE001 - best-effort per match
        log.warning("odds fetch failed for match %s: %s", m.id, exc)
        return False
    if med is None:
        return False
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
            snapshot_phase=phase,
        )
    )
    return True


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
            if _snapshot_match(db, m, api_key, now):
                summary["matches_priced"] += 1
            else:
                summary["matches_skipped"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the pass itself must never raise
        db.rollback()
        log.warning("odds refresh aborted: %s", exc)
        return {"matches_priced": 0, "matches_skipped": summary["matches_skipped"],
                "error": str(exc)}
    return summary


def snapshot_phased_odds(db: Session, api_key: str, budget: int = MAX_FETCHES_PER_PASS,
                         now: datetime | None = None) -> dict:
    """Hourly phased odds pass: capture at most one row per match per due
    band (pipeline.ingest.odds_phases), building the closing-line archive
    instead of refresh_odds' single row per match per day. NEVER raises
    (FR-4.2).

    For every scheduled match inside the 48h window, the match's current
    pre-kickoff band is compared against the phases already captured for it
    (a query per match against ix_odds_match_phase); a match whose band is
    already archived is skipped without a fetch. Due matches are fetched
    closest-kickoff-first and capped at ``budget`` fetches per pass — the
    api-sports free tier can't afford an unbounded hourly pass. Anything past
    the cap is left for a later pass and counted in ``budget_skipped``.

    DUPLICATES ARE TOLERATED BY DESIGN: there's no unique constraint on
    (match_id, snapshot_phase), so an overlapping pass (this cron plus a
    manual workflow_dispatch, say) can rarely write two rows for the same
    band. That's fine — run_market_benchmark.market_record always resolves
    to the latest row per phase, and the extra api-sports call is negligible
    against the daily quota below.

    QUOTA: at most 5 fetches per match over its lifetime (one per band).
    This pass and the daily refresh_odds pass share api-sports' free tier
    (~100 req/day) — MAX_FETCHES_PER_PASS=40 leaves headroom for both plus
    the live/lineups paths. On quota exhaustion, fetches simply fail (the
    per-match best-effort contract below), so nothing is written for that
    match this pass; a still-due band is picked up on a later hourly pass
    (self-healing for the wider bands), but a band narrow enough to fully
    elapse during an exhausted day (t1, closing) can be permanently missed —
    market_record's pre-kickoff fallback absorbs that gap.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    summary = {"matches_priced": 0, "matches_skipped": 0, "budget_skipped": 0}
    try:
        matches = (
            db.query(Match)
            .filter(
                Match.status == "scheduled",
                Match.team_home_id.isnot(None),
                Match.team_away_id.isnot(None),
                Match.kickoff_utc.isnot(None),
                Match.kickoff_utc >= now,
                Match.kickoff_utc <= now + timedelta(hours=WINDOW_HOURS),
            )
            .order_by(Match.kickoff_utc.asc(), Match.id.asc())
            .all()
        )

        due: list[tuple[Match, str]] = []
        for m in matches:
            kickoff = m.kickoff_utc if m.kickoff_utc.tzinfo else m.kickoff_utc.replace(
                tzinfo=timezone.utc)  # SQLite drops tzinfo
            hours_to_kickoff = (kickoff - now).total_seconds() / 3600.0
            # No unique constraint on (match_id, snapshot_phase) — an overlapping
            # pass can rarely add a duplicate for a band already in this set.
            # Tolerated by design (see docstring); we just skip re-fetching it.
            existing_phases = {
                row[0] for row in
                db.query(Odds.snapshot_phase)
                .filter(Odds.match_id == m.id, Odds.snapshot_phase.isnot(None))
                .distinct()
                .all()
            }
            phase = due_phase(hours_to_kickoff, existing_phases)
            if phase is not None:
                due.append((m, phase))  # already closest-kickoff-first (query order)

        budget_skipped = max(0, len(due) - budget)
        if budget_skipped:
            log.warning("odds phased snapshot: budget cap (%d) reached, %d due match(es) skipped",
                        budget, budget_skipped)
        summary["budget_skipped"] = budget_skipped

        for m, phase in due[:budget]:
            if _snapshot_match(db, m, api_key, now, phase=phase):
                summary["matches_priced"] += 1
            else:
                summary["matches_skipped"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the pass itself must never raise
        db.rollback()
        log.warning("odds phased snapshot aborted: %s", exc)
        return {"matches_priced": 0, "matches_skipped": summary["matches_skipped"],
                "budget_skipped": summary["budget_skipped"], "error": str(exc)}
    return summary


def backfill_finished_odds(db: Session, api_key: str,
                           max_age_days: float = BACKFILL_DAYS) -> dict:
    """Outage recovery: price recently FINISHED matches that never got a
    pre-kickoff snapshot (e.g. the scheduler was down through kickoff).

    api-sports serves a fixture's frozen pre-match odds for ~7 days after
    full time, so the prices stored here are still the pre-match consensus —
    only captured_at is honest (post-match), which keeps these rows out of
    the pre-kickoff model-vs-market record while letting the match page show
    the comparison. A match already holding an implied 1X2 triple is left
    alone. Same best-effort contract as refresh_odds: NEVER raises.
    """
    now = datetime.now(timezone.utc)
    summary = {"matches_priced": 0, "matches_skipped": 0}
    try:
        has_triple = (
            db.query(Odds.id)
            .filter(Odds.match_id == Match.id, Odds.implied_prob_home.isnot(None))
            .exists()
        )
        matches = (
            db.query(Match)
            .filter(
                Match.status == "finished",
                Match.team_home_id.isnot(None),
                Match.team_away_id.isnot(None),
                Match.kickoff_utc.isnot(None),
                Match.kickoff_utc >= now - timedelta(days=max_age_days),
                ~has_triple,
            )
            .order_by(Match.kickoff_utc.asc(), Match.id.asc())
            .all()
        )
        for m in matches:
            if _snapshot_match(db, m, api_key, now):
                summary["matches_priced"] += 1
            else:
                summary["matches_skipped"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the pass itself must never raise
        db.rollback()
        log.warning("odds backfill aborted: %s", exc)
        return {"matches_priced": 0, "matches_skipped": summary["matches_skipped"],
                "error": str(exc)}
    return summary
