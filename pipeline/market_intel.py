"""Hourly prediction-market odds snapshot (spec 2026-07-10): the intel panel's data.

Fetch+parse ACTIVE markets per SourceConfig, map them onto our matches/teams
by normalized name, de-vig within each market group, then delete-then-insert
per (sport, source, hour) so re-runs stay idempotent (same pattern as
prob_snapshots._replace_day). BEST-EFFORT BY CONTRACT: a malformed market
skips that market, a dead source skips that source; run() raises only when
ALL sources yield zero rows — the workflow should go red then, and only then.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.models import MarketOddsSnapshot, Match, SportMatch, SportTeam, Team
from pipeline.ingest import kalshi, polymarket
from pipeline.ingest.market_names import build_team_index, normalize

log = logging.getLogger(__name__)

RETENTION_DAYS = 14
#: Title groups whose mapped outcomes sum below this keep raw prices —
#: rescaling an incomplete outcome set would inflate every probability.
_DEVIG_FLOOR = 0.9


@dataclass(frozen=True)
class SourceConfig:
    sport: str
    source: str
    #: () -> parsed neutral rows (adapter fetch+parse composed; see CONFIGS).
    load: Callable[[], list[dict]]


def _load_polymarket(tag_slug: str) -> list[dict]:
    return polymarket.parse_events(polymarket.fetch_events(tag_slug))


def _load_kalshi_leg(series_ticker: str, kind: str) -> list[dict]:
    """One Kalshi series, isolated: a dead/renamed series (e.g. a title-series
    ticker 404ing) must not take down the other leg — each series is an
    independent HTTP call and either can be wrong without the other being."""
    try:
        return kalshi.parse_markets(kalshi.fetch_markets(series_ticker), kind)
    except Exception:
        log.exception("market intel: kalshi %s leg (%s) failed", kind, series_ticker)
        return []


def _load_kalshi_wc() -> list[dict]:
    return (_load_kalshi_leg(kalshi.WC_MATCH_SERIES, "match")
            + _load_kalshi_leg(kalshi.WC_TITLE_SERIES, "title"))


CONFIGS: list[SourceConfig] = [
    SourceConfig("football", "polymarket",
                 lambda: _load_polymarket(polymarket.WC_TAG_SLUG)),
    SourceConfig("nrl", "polymarket",
                 lambda: _load_polymarket(polymarket.NRL_TAG_SLUG)),
    SourceConfig("football", "kalshi", _load_kalshi_wc),
]


def _fixtures(db: Session, sport: str) -> dict[tuple[str, str], tuple[int, bool]]:
    """{(norm_home, norm_away) -> (match_id, reversed)} for scheduled fixtures."""
    index: dict[tuple[str, str], tuple[int, bool]] = {}
    if sport == "football":
        names = dict(db.query(Team.id, Team.name).all())
        matches = (db.query(Match)
                   .filter(Match.status == "scheduled",
                           Match.team_home_id.isnot(None),
                           Match.team_away_id.isnot(None)).all())
        pairs = [(m.id, names.get(m.team_home_id), names.get(m.team_away_id))
                 for m in matches]
    else:
        names = dict(db.query(SportTeam.id, SportTeam.name)
                     .filter(SportTeam.sport == sport).all())
        matches = (db.query(SportMatch)
                   .filter(SportMatch.sport == sport,
                           SportMatch.status == "scheduled",
                           SportMatch.home_team_id.isnot(None),
                           SportMatch.away_team_id.isnot(None)).all())
        pairs = [(m.id, names.get(m.home_team_id), names.get(m.away_team_id))
                 for m in matches]
    for match_id, home, away in pairs:
        if not home or not away:
            continue
        h, a = normalize(home), normalize(away)
        index[(h, a)] = (match_id, False)
        index[(a, h)] = (match_id, True)
    return index


def _team_index(db: Session, sport: str) -> dict[str, int]:
    if sport == "football":
        return build_team_index(db.query(Team.id, Team.name).all())
    return build_team_index(
        db.query(SportTeam.id, SportTeam.name).filter(SportTeam.sport == sport).all())


def _to_rows(db: Session, sport: str, parsed: list[dict],
             fetched_at: datetime) -> list[MarketOddsSnapshot]:
    fixtures = _fixtures(db, sport)
    teams = _team_index(db, sport)
    out: list[MarketOddsSnapshot] = []

    groups: dict[str, list[dict]] = {}
    for r in parsed:
        groups.setdefault(f"{r['kind']}:{r['group']}", []).append(r)

    for key, rows in groups.items():
        kind = rows[0]["kind"]
        if kind == "match":
            outcomes = {r["outcome"] for r in rows}
            required = {"home", "draw", "away"} if sport == "football" else {"home", "away"}
            if not required <= outcomes:
                log.info("market intel: incomplete group %s (%s) skipped", key, outcomes)
                continue
            hit = fixtures.get((normalize(rows[0]["home_name"]),
                                normalize(rows[0]["away_name"])))
            if hit is None:
                log.info("market intel: no fixture for group %s", key)
                continue
            match_id, reversed_ = hit
            total = sum(r["price"] for r in rows)
            if total <= 0:
                continue
            flip = {"home": "away", "away": "home", "draw": "draw"}
            for r in rows:
                outcome = flip[r["outcome"]] if reversed_ else r["outcome"]
                out.append(MarketOddsSnapshot(
                    sport=sport, source=r["source"], market_type="match_winner",
                    match_id=match_id, team_id=None, outcome=outcome,
                    implied_prob=r["price"] / total,
                    external_id=r["external_id"], fetched_at=fetched_at))
        else:  # title
            mapped = [(r, teams.get(normalize(r["team_name"] or ""))) for r in rows]
            for r, team_id in mapped:
                if team_id is None:
                    log.info("market intel: unmapped title team %r", r["team_name"])
            mapped = [(r, tid) for r, tid in mapped if tid is not None]
            total = sum(r["price"] for r, _ in mapped)
            scale = total if total >= _DEVIG_FLOOR else 1.0
            for r, team_id in mapped:
                out.append(MarketOddsSnapshot(
                    sport=sport, source=r["source"], market_type="title_winner",
                    match_id=None, team_id=team_id, outcome="win",
                    implied_prob=r["price"] / scale,
                    external_id=r["external_id"], fetched_at=fetched_at))
    return out


def _replace_hour(db: Session, sport: str, source: str, hour: datetime,
                  rows: list[MarketOddsSnapshot]) -> int:
    db.query(MarketOddsSnapshot).filter(
        MarketOddsSnapshot.sport == sport,
        MarketOddsSnapshot.source == source,
        MarketOddsSnapshot.fetched_at == hour,
    ).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    return len(rows)


def _prune(db: Session, now: datetime) -> None:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    db.query(MarketOddsSnapshot).filter(
        MarketOddsSnapshot.fetched_at < cutoff).delete(synchronize_session=False)
    db.commit()


def run(db: Session, now: datetime) -> int:
    hour = now.replace(minute=0, second=0, microsecond=0)
    total = 0
    for cfg in CONFIGS:
        try:
            rows = _to_rows(db, cfg.sport, cfg.load(), hour)
            total += _replace_hour(db, cfg.sport, cfg.source, hour, rows)
            log.info("market intel: %s/%s wrote %d rows", cfg.source, cfg.sport, len(rows))
        except Exception:
            db.rollback()
            log.exception("market intel: %s/%s failed", cfg.source, cfg.sport)
    _prune(db, now)
    if total == 0:
        raise RuntimeError("market intel: no rows ingested from any source")
    return total


if __name__ == "__main__":
    from datetime import timezone

    from app.db import SessionLocal

    logging.basicConfig(level=logging.INFO)
    session = SessionLocal()
    try:
        run(session, datetime.now(timezone.utc))
    finally:
        session.close()
