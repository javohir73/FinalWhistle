"""Persist validation observations. Append-only, idempotent, isolated.

Hard boundaries, each enforced by a test:
  - Writes ONLY `validation_fixture_observation` and
    `validation_market_snapshot`. Never `odds` (the pre-registered
    API-Football baseline the q3 benchmark reads) and never
    `market_odds_snapshots` (the intel product surface, which is replaced
    hourly and swept by a retention prune).
  - Append-only. A re-observed payload is a no-op via the uniqueness key; a
    CHANGED payload appends a new row and leaves the original readable. Nothing
    is ever updated or deleted, and there is no retention sweep.
  - De-vig happens WITHIN one (source, event, bookmaker) group only. A
    cross-source consensus would be a new predictor, not evidence, so it is
    never computed here.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    Match,
    Team,
    Tournament,
    ValidationFixtureObservation,
    ValidationMarketSnapshot,
)
from pipeline.ingest.validation.identity import MatchCandidate, resolve

log = logging.getLogger(__name__)

#: Bundesliga only. Pooling other competitions is forbidden, and an unscoped
#: candidate search would let an EPL or WC26 fixture with the same club names
#: and a nearby kickoff steal a Bundesliga observation.
DEFAULT_TOURNAMENT = "Bundesliga 2026-27"

#: Domains enforced before storage. Anything outside them is a programming
#: error in this package, not provider noise, so it raises rather than skips.
VALID_SOURCES = frozenset({"football_data_org", "openligadb",
                           "the_odds_api", "betfair_historical"})
VALID_OUTCOMES = frozenset({"home", "draw", "away"})
VALID_RECONCILIATION = frozenset({"matched", "unmatched", "conflict"})


def _candidates(db: Session, tournament_name: str | None = None
                ) -> list[MatchCandidate]:
    """Our Match rows as identity candidates, SCOPED TO ONE TOURNAMENT.

    Scoping is not cosmetic: without it a Premier League or WC26 fixture with
    the same canonical club names and a kickoff inside the tolerance window
    could capture a Bundesliga observation. Reads Team.name directly, since
    club rows already carry the canonical spelling identity.ALIASES targets.
    """
    name = tournament_name or DEFAULT_TOURNAMENT
    rows = []
    q = (db.query(Match)
         .join(Tournament, Tournament.id == Match.tournament_id)
         .filter(Tournament.name == name,
                 Match.team_home_id.isnot(None),
                 Match.team_away_id.isnot(None)))
    for m in q.all():
        home = db.get(Team, m.team_home_id)
        away = db.get(Team, m.team_away_id)
        if home is None or away is None:
            continue
        rows.append(MatchCandidate(m.id, home.name, away.name, m.kickoff_utc))
    return rows


def _exists_fixture(db: Session, obs) -> bool:
    return db.query(ValidationFixtureObservation).filter_by(
        source=obs.source, source_event_id=obs.source_event_id,
        payload_sha256=obs.payload_sha256).first() is not None


def _exists_market(db: Session, obs) -> bool:
    return db.query(ValidationMarketSnapshot).filter_by(
        source=obs.source, source_market_id=obs.source_market_id,
        outcome=obs.outcome, captured_at=obs.captured_at,
        bookmaker_key=obs.bookmaker_key).first() is not None


def _check_domains(source: str, status: str, outcome: str | None = None) -> None:
    if source not in VALID_SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(VALID_SOURCES)}")
    if status not in VALID_RECONCILIATION:
        raise ValueError(f"bad reconciliation status {status!r}")
    if outcome is not None and outcome not in VALID_OUTCOMES:
        raise ValueError(f"bad outcome {outcome!r}; expected one of {sorted(VALID_OUTCOMES)}")


def _valid_price(price) -> bool:
    """A decimal price must be finite and strictly greater than 1.0.

    1.0 implies a certainty and anything below it is nonsense; NaN/inf would
    poison every downstream probability. Rejected BEFORE storage so the table
    never holds a price that cannot be inverted.
    """
    return (price is not None and isinstance(price, (int, float))
            and math.isfinite(price) and price > 1.0)


def load_fixture_observations(db: Session, observations, *,
                              retrieved_at: datetime | None = None,
                              tournament_name: str | None = None) -> dict:
    """Append fixture observations, resolving identity for each."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    cands = _candidates(db, tournament_name)
    stats = {"seen": 0, "inserted": 0, "duplicate": 0,
             "matched": 0, "unmatched": 0, "conflict": 0}

    for obs in observations:
        stats["seen"] += 1
        if _exists_fixture(db, obs):
            stats["duplicate"] += 1
            continue
        r = resolve(obs.raw_home_label, obs.raw_away_label, obs.kickoff_utc, cands)
        _check_domains(obs.source, r.status)
        stats[r.status] += 1
        db.add(ValidationFixtureObservation(
            source=obs.source, source_event_id=obs.source_event_id,
            competition_code=obs.competition_code, season=obs.season,
            kickoff_utc=obs.kickoff_utc,
            raw_home_label=obs.raw_home_label, raw_away_label=obs.raw_away_label,
            canonical_home=r.canonical_home, canonical_away=r.canonical_away,
            match_id=r.match_id, status=obs.status,
            score_home=obs.score_home, score_away=obs.score_away,
            source_updated_at=obs.source_updated_at, retrieved_at=retrieved_at,
            payload_sha256=obs.payload_sha256,
            reconciliation_status=r.status, reconciliation_note=r.note,
        ))
        stats["inserted"] += 1
    db.commit()
    return stats


def _devig_group(rows: list) -> dict[str, float]:
    """Proportional de-vig within ONE source+market group. {} if incomplete.

    Requires all three outcomes: a partial book cannot be de-vigged without
    inventing the missing leg.
    """
    by_outcome = {r.outcome: r.price_decimal for r in rows}
    if set(by_outcome) != {"home", "draw", "away"}:
        return {}
    if not all(_valid_price(p) for p in by_outcome.values()):
        return {}
    raw = {k: 1.0 / p for k, p in by_outcome.items()}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else {}


def load_market_observations(db: Session, observations, *,
                             retrieved_at: datetime | None = None,
                             tournament_name: str | None = None) -> dict:
    """Append market snapshots, de-vigging within each source+market group."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    cands = _candidates(db, tournament_name)
    stats = {"seen": 0, "inserted": 0, "duplicate": 0, "rejected_price": 0,
             "matched": 0, "unmatched": 0, "conflict": 0, "devigged_groups": 0}

    groups: dict[tuple, list] = {}
    for obs in observations:
        groups.setdefault(
            (obs.source, obs.source_market_id, obs.bookmaker_key, obs.captured_at),
            []).append(obs)

    for _key, rows in groups.items():
        # Reject unusable prices BEFORE they can reach storage or a de-vig.
        usable = [r for r in rows if _valid_price(r.price_decimal)]
        stats["rejected_price"] += len(rows) - len(usable)
        stats["seen"] += len(rows) - len(usable)
        rows = usable
        if not rows:
            continue
        devig = _devig_group(rows)
        if devig:
            stats["devigged_groups"] += 1
        for obs in rows:
            stats["seen"] += 1
            if _exists_market(db, obs):
                stats["duplicate"] += 1
                continue
            r = resolve(obs.raw_home_label, obs.raw_away_label, obs.kickoff_utc, cands)
            _check_domains(obs.source, r.status, obs.outcome)
            stats[r.status] += 1
            price = obs.price_decimal
            prob = devig.get(obs.outcome)
            if prob is not None and not (0.0 < prob < 1.0):
                raise ValueError(f"de-vigged probability out of range: {prob!r}")
            db.add(ValidationMarketSnapshot(
                source=obs.source, source_market_id=obs.source_market_id,
                source_event_id=obs.source_event_id,
                competition_code=obs.competition_code, kickoff_utc=obs.kickoff_utc,
                raw_home_label=obs.raw_home_label, raw_away_label=obs.raw_away_label,
                canonical_home=r.canonical_home, canonical_away=r.canonical_away,
                match_id=r.match_id, bookmaker_key=obs.bookmaker_key or "",
                outcome=obs.outcome, price_decimal=price,
                implied_prob_raw=(1.0 / price) if price and price > 1.0 else None,
                implied_prob_devig=prob,
                captured_at=obs.captured_at, retrieved_at=retrieved_at,
                payload_sha256=obs.payload_sha256,
                archive_sha256=obs.archive_sha256,
                acquisition_note=obs.acquisition_note,
                reconciliation_status=r.status, reconciliation_note=r.note,
            ))
            stats["inserted"] += 1
    db.commit()
    return stats
