"""Shared 'last N finished results for one NRL team' helper. Used by both the
offline preview-text generator (pipeline/sports/nrl_predict.py) and the
online match-detail endpoint (backend/app/api/nrl_intel.py) so the two never
disagree on what "recent form" means.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import SportMatch

SPORT = "nrl"


def _kickoff_key(m: SportMatch) -> tuple:
    """Sort/comparison key, normalized to naive UTC.

    SQLite's DateTime(timezone=True) column doesn't actually round-trip
    tzinfo: an ORM instance still resident in the session's identity map
    (kept alive by some other reference) retains its original
    timezone-aware value, while a freshly reloaded row comes back naive --
    same underlying timestamp, inconsistent tzinfo-ness depending on GC
    timing. Stripping tzinfo here (after normalizing to UTC first, in case
    a caller ever passes a non-UTC aware datetime) keeps every comparison
    naive-vs-naive so `last_n_results`' `before` filter never raises
    `TypeError: can't compare offset-naive and offset-aware datetimes`.
    """
    kickoff = m.kickoff_utc
    if kickoff is not None and kickoff.tzinfo is not None:
        kickoff = kickoff.astimezone(timezone.utc).replace(tzinfo=None)
    return (kickoff is None, kickoff or datetime.min, m.id)


def last_n_results(
    db: Session, team_id: int, n: int = 5, before: SportMatch | None = None
) -> list[dict]:
    """Most recent `n` FINISHED matches for `team_id`, most recent first. Each
    row: {round, opponent_id, for, against, result: "W"|"L"|"D", kickoff_utc}.
    `before`: when given, only matches strictly earlier than its kickoff
    (falls back to id ordering for same/null kickoff) are eligible -- lets a
    fixture compute its own pre-match form without seeing itself or later
    matches.
    """
    matches = (
        db.query(SportMatch)
        .filter(
            SportMatch.sport == SPORT,
            SportMatch.status == "finished",
            SportMatch.score_home.isnot(None),
            SportMatch.score_away.isnot(None),
            or_(SportMatch.home_team_id == team_id, SportMatch.away_team_id == team_id),
        )
        .all()
    )
    if before is not None:
        cutoff = _kickoff_key(before)
        matches = [m for m in matches if _kickoff_key(m) < cutoff]
    matches.sort(key=_kickoff_key, reverse=True)
    matches = matches[:n]

    out = []
    for m in matches:
        was_home = m.home_team_id == team_id
        sf, sa = (m.score_home, m.score_away) if was_home else (m.score_away, m.score_home)
        result = "W" if sf > sa else "L" if sf < sa else "D"
        out.append({
            "round": m.round,
            "opponent_id": m.away_team_id if was_home else m.home_team_id,
            "for": sf,
            "against": sa,
            "result": result,
            "kickoff_utc": m.kickoff_utc,
        })
    return out


def form_averages(results: list[dict]) -> dict:
    """avg_for/avg_against/avg_margin over `results` (empty -> zeros)."""
    if not results:
        return {"avg_for": 0.0, "avg_against": 0.0, "avg_margin": 0.0}
    n = len(results)
    total_for = sum(r["for"] for r in results)
    total_against = sum(r["against"] for r in results)
    return {
        "avg_for": round(total_for / n, 1),
        "avg_against": round(total_against / n, 1),
        "avg_margin": round((total_for - total_against) / n, 1),
    }
