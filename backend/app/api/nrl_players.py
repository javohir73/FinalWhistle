"""Try-scorer projections (Wave 3): GET /api/nrl/matches/{id}/scorers.

Combines this match's nrl_team_lists (real, Wave-3-owned) with try-scorer
history (nrl_try_events) via pipeline.sports.nrl_scorer_model. Probabilities
only -- no odds, no value badges (program-wide constraint).

NrlTryEvent/NrlTeamList are the real app.models tables. Note: until a real
team-list source lands (NrlComStatsProvider.fetch_team_list is an
honest-empty stub), nrl_team_lists has no producer in production, so this
endpoint returns [] -- the UI renders nothing for the section.

Returns a BARE ARRAY (the spec's frozen contract), not an object -- so
there is no room for a top-level disclaimer key here (the page's footer
disclaimer already covers every NRL page, per Global Constraints). Each
entry adds one field beyond the spec's literal list: "team" ("home" |
"away"), purely additive and necessary since jersey numbers repeat across
both teams and the spec's array has no other way to split them.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NrlTeamList, NrlTryEvent, SportMatch, SportTeam
from pipeline.sports.nrl_scorer_model import project_scorer

router = APIRouter(prefix="/api/nrl", tags=["nrl-players"])

LAST_N_ROUNDS = 10
UNIT_BY_POSITION = {
    "FB": "outside backs", "WG": "outside backs", "CE": "outside backs",
    "FE": "halves", "HB": "halves", "HK": "hooker",
}
DEFAULT_UNIT = "forwards"


def _unit_for(position: str) -> str:
    return UNIT_BY_POSITION.get(position, DEFAULT_UNIT)


def _last10_for(db: Session, team: str, player: str, before_round: int | None) -> list[dict]:
    q = (
        db.query(SportMatch.round, NrlTryEvent.id)
        .join(NrlTryEvent, NrlTryEvent.match_id == SportMatch.id)
        .filter(NrlTryEvent.team == team, NrlTryEvent.player == player)
    )
    if before_round is not None:
        q = q.filter(SportMatch.round < before_round)
    rows = q.order_by(SportMatch.round.desc()).limit(LAST_N_ROUNDS).all()
    by_round: dict[int, int] = defaultdict(int)
    for round_no, _id in rows:
        by_round[round_no] += 1
    return [{"round": r, "tries": n} for r, n in sorted(by_round.items())]


@router.get("/matches/{match_id}/scorers")
def nrl_match_scorers(match_id: int, db: Session = Depends(get_db)) -> list[dict]:
    match = db.query(SportMatch).filter_by(id=match_id, sport="nrl").one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail={
            "code": "no_nrl_match", "message": "No NRL match with that id",
        })

    home_name = db.query(SportTeam.name).filter_by(id=match.home_team_id).scalar() \
        if match.home_team_id is not None else None
    away_name = db.query(SportTeam.name).filter_by(id=match.away_team_id).scalar() \
        if match.away_team_id is not None else None

    scorers: list[dict] = []
    for entry in db.query(NrlTeamList).filter_by(match_id=match_id).all():
        if entry.team == away_name:
            side, opponent = "away", home_name
        else:
            side, opponent = "home", away_name  # best-effort default if names don't line up yet

        last10 = _last10_for(db, entry.team, entry.player, before_round=match.round)
        tries_last10 = [row["tries"] for row in last10]
        games_season = (
            db.query(SportMatch.id)
            .join(NrlTeamList, NrlTeamList.match_id == SportMatch.id)
            .filter(NrlTeamList.team == entry.team, NrlTeamList.player == entry.player,
                    SportMatch.season == match.season)
            .count()
        )
        tries_season = (
            db.query(NrlTryEvent.id)
            .join(SportMatch, SportMatch.id == NrlTryEvent.match_id)
            .filter(NrlTryEvent.team == entry.team, NrlTryEvent.player == entry.player,
                    SportMatch.season == match.season)
            .count()
        )
        p_anytime = (
            project_scorer(db, opponent_team=opponent, position=entry.position,
                            last10_tries=tries_last10, tries_season=tries_season,
                            games_season=games_season)
            if opponent else 0.0
        )
        scorers.append({
            "player": entry.player, "jersey": entry.jersey, "position": entry.position,
            "unit": _unit_for(entry.position), "tries_season": tries_season,
            "games_season": games_season, "last10": last10, "p_anytime": p_anytime,
            "team": side,
        })
    return scorers
