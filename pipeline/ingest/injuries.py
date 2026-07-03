"""Pre-match injury/availability snapshot from API-Football, per fixture.

Mirrors pipeline.ingest.odds.refresh_odds: for every scheduled match with both
teams kicking off inside the window, resolve the provider fixture id, fetch its
injuries, and store a normalized per-side list on Match.injuries (feeding the
day-ahead availability adjustment). BEST-EFFORT BY CONTRACT — any fetch failure
or malformed answer leaves that match unchanged and refresh_injuries NEVER raises
to callers, so prediction generation is unblockable by the feed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Match, Team
from pipeline.ingest.api_football import fetch_injuries, parse_injuries
from pipeline.team_mapping import normalize_team_name

log = logging.getLogger(__name__)

WINDOW_HOURS = 48.0


def _fixture_id(db: Session, match: Match, api_key: str) -> int | None:
    """Provider fixture id: the stored one, else the lineups path's resolver
    (team pair + kickoff date). Mirrors pipeline.ingest.odds._fixture_id."""
    if match.provider_fixture_id is not None:
        return match.provider_fixture_id
    from app.lineups import _resolve_fixture_id

    return _resolve_fixture_id(db, match, api_key)


def refresh_injuries(db: Session, api_key: str, window_hours: float = WINDOW_HOURS) -> dict:
    """One best-effort injuries pass over upcoming matches. NEVER raises.

    For each scheduled match kicking off inside ``window_hours`` it fetches the
    fixture's injuries and sets ``Match.injuries`` to a per-side list (``[]`` when
    the fixture is checked but clear). A match whose fixture can't be resolved or
    whose feed errors is skipped silently, leaving its ``injuries`` untouched.
    """
    now = datetime.now(timezone.utc)
    summary = {"matches_injuries": 0, "matches_skipped": 0}
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
                records = parse_injuries(fetch_injuries(api_key, fid))
            except Exception as exc:  # noqa: BLE001 - best-effort per match
                log.warning("injuries fetch failed for match %s: %s", m.id, exc)
                summary["matches_skipped"] += 1
                continue
            home = db.get(Team, m.team_home_id)
            away = db.get(Team, m.team_away_id)
            hn = normalize_team_name(home.name) if home else None
            an = normalize_team_name(away.name) if away else None
            injuries: list[dict] = []
            for r in records:
                tn = normalize_team_name(r["team_name"]) if r.get("team_name") else None
                side = "home" if tn == hn else "away" if tn == an else None
                if side is None:
                    continue
                injuries.append({
                    "provider_player_id": r["provider_player_id"], "name": r["name"],
                    "type": r["type"], "reason": r["reason"], "side": side,
                })
            m.injuries = injuries
            summary["matches_injuries"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the pass itself must never raise
        db.rollback()
        log.warning("injuries refresh aborted: %s", exc)
        return {"matches_injuries": 0, "matches_skipped": summary["matches_skipped"],
                "error": str(exc)}
    return summary
