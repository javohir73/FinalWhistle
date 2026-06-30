"""Goalscorer-data ingestion helpers (Phase 2). Stage 1a ships only the team-id
linker; squad + per-player stats ingestion arrive in Stage 1b."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Player, Team
from pipeline.ingest.api_football import fetch_player_stats, fetch_squad, fetch_teams
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)


_POSITION_MAP = {"Goalkeeper": "G", "Defender": "D", "Midfielder": "M", "Attacker": "F"}


def _squad_position(pos: str | None) -> str | None:
    """Map an api-sports squad position word to our G/D/M/F code (None if unknown)."""
    return _POSITION_MAP.get(pos or "")


def ingest_squad(db: Session, api_key: str, team: Team) -> int:
    """Upsert Player rows (identity + position) for one team's squad, keyed on
    provider_player_id. Returns the number of squad players seen. No stats here."""
    if team.provider_team_id is None:
        return 0
    response = fetch_squad(api_key, team.provider_team_id)
    squad_players = (response[0].get("players") if response else None) or []
    seen = 0
    for p in squad_players:
        pid = p.get("id")
        if pid is None:
            continue
        row = db.query(Player).filter_by(provider_player_id=pid).one_or_none()
        if row is None:
            row = Player(provider_player_id=pid)
            db.add(row)
        if p.get("name"):
            row.name = p["name"]
        row.team_id = team.id
        mapped = _squad_position(p.get("position"))
        if mapped is not None:
            row.position = mapped
        seen += 1
    db.commit()
    return seen


def _aggregate_stats(statistics: list[dict] | None, league_id: int | None = None) -> tuple[int, int, int]:
    """Sum goals.total, games.minutes and penalty.scored across a player's
    statistics entries (api-sports returns one per team+league). Nulls count as 0.
    When league_id is given, only that league's entries are summed."""
    goals = minutes = pens = 0
    for s in statistics or []:
        if league_id is not None and (s.get("league") or {}).get("id") != league_id:
            continue
        goals += (s.get("goals") or {}).get("total") or 0
        minutes += (s.get("games") or {}).get("minutes") or 0
        pens += (s.get("penalty") or {}).get("scored") or 0
    return goals, minutes, pens


def ingest_player_stats(
    db: Session, api_key: str, player: Player,
    club_season: int, wc_season: int, wc_league: int,
) -> None:
    """Fill one Player's club-season and WC scoring stats. Club = sum of all
    club_season entries; WC = sum of wc_season entries for the WC league only."""
    player.club_goals = player.club_minutes = player.club_penalties = 0
    player.wc_goals = player.wc_minutes = 0
    club = fetch_player_stats(api_key, player.provider_player_id, club_season)
    if club:
        cg, cm, cp = _aggregate_stats(club[0].get("statistics"))
        player.club_goals, player.club_minutes, player.club_penalties = cg, cm, cp
        player.season = club_season
    wc = fetch_player_stats(api_key, player.provider_player_id, wc_season)
    if wc:
        wg, wm, _pens = _aggregate_stats(wc[0].get("statistics"), league_id=wc_league)
        player.wc_goals, player.wc_minutes = wg, wm
    player.updated_at = datetime.now(timezone.utc)
    db.commit()


def link_team_ids(db: Session, teams_response: list[dict]) -> int:
    """Set Team.provider_team_id from an api-sports /teams response, matching on
    the normalized team name. Returns the number of Team rows linked. Unknown
    provider teams are ignored (never create a Team)."""
    by_norm = {normalize_team_name(t.name): t for t in db.query(Team).all()}
    linked = 0
    for entry in teams_response or []:
        team = entry.get("team") or {}
        pid, pname = team.get("id"), team.get("name")
        if pid is None or not pname:
            continue
        row = by_norm.get(normalize_team_name(pname))
        if row is not None and row.provider_team_id != pid:
            row.provider_team_id = pid
            linked += 1
    db.commit()
    return linked


def refresh_players(
    db: Session, api_key: str, league: int,
    club_season: int = 2025, wc_season: int = 2026,
    max_players: int = 40, stale_days: int = 7, pace_seconds: float = 0.5,
    now: datetime | None = None,
) -> dict:
    """One bounded, idempotent ingestion pass (runs server-side; the cron repeats
    it to cover everyone). Links team ids, ingests squads for teams with no Player
    rows yet, then refreshes up to max_players players whose stats are missing or
    older than stale_days. Paced; a single player's failure never aborts the run."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=stale_days)

    teams_linked = link_team_ids(db, fetch_teams(api_key, league, wc_season))

    squads_ingested = 0
    for team in db.query(Team).filter(Team.provider_team_id.isnot(None)).all():
        has_players = db.query(Player).filter_by(team_id=team.id).first() is not None
        if not has_players:
            ingest_squad(db, api_key, team)
            squads_ingested += 1

    stale = (
        db.query(Player)
        .filter((Player.updated_at.is_(None)) | (Player.updated_at < cutoff))
        .order_by(Player.updated_at.is_(None).desc(), Player.id)
        .limit(max_players)
        .all()
    )
    refreshed = 0
    for player in stale:
        try:
            ingest_player_stats(db, api_key, player, club_season, wc_season, league)
            refreshed += 1
        except Exception:  # noqa: BLE001 - one bad player must not abort the pass
            log.warning("player stats refresh failed for %s", player.provider_player_id)
        time.sleep(pace_seconds)

    return {"teams_linked": teams_linked, "squads_ingested": squads_ingested,
            "players_refreshed": refreshed}
