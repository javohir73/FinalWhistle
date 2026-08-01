"""Historical club results sourced from API-Football fixture payloads.

Domestic league ratings use football-data.co.uk division CSVs. A cross-border
competition has no single domestic division, so the Champions League reuses
its already-configured API-Football identity for a bounded, idempotent history
backfill. The pure parser and injectable fetcher keep tests network-free.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team
from pipeline.ingest.api_football import fetch_fixtures
from pipeline.team_mapping import normalize_team_name

_FINISHED = frozenset({"FT", "AET", "PEN", "AWD", "WO"})


def _score_90(fixture: dict) -> tuple[int, int] | None:
    """Prefer the regulation/full-time pair; fall back to final goals.

    API-Football separates ``score.fulltime`` from ``score.extratime`` and
    ``score.penalty``. The model predicts the 90-minute result, so an AET/PEN
    tie must not be trained on its post-regulation total.
    """
    fulltime = (fixture.get("score") or {}).get("fulltime") or {}
    home, away = fulltime.get("home"), fulltime.get("away")
    if home is None or away is None:
        goals = fixture.get("goals") or {}
        home, away = goals.get("home"), goals.get("away")
    if not isinstance(home, int) or not isinstance(away, int):
        return None
    return home, away


def parse_finished_fixtures(fixtures: list[dict]) -> list[dict]:
    """Return validated, regulation-time historical rows from raw fixtures."""
    rows: list[dict] = []
    for raw in fixtures or []:
        fixture = raw.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short")
        if status not in _FINISHED:
            continue
        fixture_id, date_raw = fixture.get("id"), fixture.get("date")
        teams = raw.get("teams") or {}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        score = _score_90(raw)
        if (
            fixture_id is None
            or not date_raw
            or home.get("id") is None
            or away.get("id") is None
            or not home.get("name")
            or not away.get("name")
            or score is None
        ):
            continue
        try:
            played_at = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        rows.append({
            "fixture_id": int(fixture_id),
            "date": played_at,
            "home_id": int(home["id"]),
            "home_name": normalize_team_name(home["name"]),
            "away_id": int(away["id"]),
            "away_name": normalize_team_name(away["name"]),
            "score_home": score[0],
            "score_away": score[1],
            # UEFA finals are neutral; other rounds retain a real home side.
            "is_neutral": str((raw.get("league") or {}).get("round") or "").strip().lower()
            == "final",
        })
    return rows


def download_finished_fixtures(
    api_key: str,
    league: int,
    seasons: tuple[int, ...],
    *,
    fetcher: Callable[..., list[dict]] | None = None,
) -> list[dict]:
    """Fetch explicit completed seasons and return one validated row list."""
    fetch = fetcher or fetch_fixtures
    rows: list[dict] = []
    for season in seasons:
        rows.extend(parse_finished_fixtures(fetch(api_key, league=league, season=season)))
    return rows


def _upsert_provider_team(db: Session, provider_id: int, name: str) -> Team:
    team = db.query(Team).filter_by(provider_team_id=provider_id).one_or_none()
    if team is None:
        team = db.query(Team).filter_by(name=name).one_or_none()
    if team is None:
        team = Team(name=name, provider_team_id=provider_id, is_host=False)
        db.add(team)
        db.flush()
    else:
        team.name = name
        team.provider_team_id = provider_id
    return team


def load_api_football_club_results(
    db: Session,
    rows: list[dict],
    *,
    competition: str,
) -> dict:
    """Load parsed API-Football rows into ``historical_matches`` idempotently."""
    existing = {
        (m.date.date().isoformat(), m.team_a_id, m.team_b_id)
        for m in db.query(HistoricalMatch).filter_by(competition=competition).all()
    }
    inserted = skipped = 0
    for row in rows:
        home = _upsert_provider_team(db, row["home_id"], row["home_name"])
        away = _upsert_provider_team(db, row["away_id"], row["away_name"])
        key = (row["date"].date().isoformat(), home.id, away.id)
        if key in existing:
            skipped += 1
            continue
        db.add(HistoricalMatch(
            date=row["date"],
            team_a_id=home.id,
            team_b_id=away.id,
            score_a=row["score_home"],
            score_b=row["score_away"],
            competition=competition,
            is_neutral=row["is_neutral"],
        ))
        existing.add(key)
        inserted += 1
    db.commit()
    return {
        "rows_in": len(rows),
        "matches_inserted": inserted,
        "skipped_dupes": skipped,
    }
