"""Knockout / tournament simulation endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.cache import cache
from app.db import get_db
from app.models import Match, Team, TournamentOdds

router = APIRouter(prefix="/api/knockout", tags=["knockout"])


@router.get("/bracket", response_model=schemas.KnockoutBracketOut)
def get_bracket(db: Session = Depends(get_db)):
    """Official knockout bracket: every KO Match row (real teams + live scores).
    Unassigned sides serialize team_id/team = null (never 'TBD'). Live feed —
    not edge-cached (see main.py no-store clause)."""
    rows = (
        db.query(Match)
        .filter(Match.stage != "group", Match.match_no.isnot(None))
        .order_by(Match.match_no)
        .all()
    )
    ties = []
    for m in rows:
        home_team = db.get(Team, m.team_home_id) if m.team_home_id else None
        away_team = db.get(Team, m.team_away_id) if m.team_away_id else None
        ties.append(
            schemas.KnockoutTieOut(
                match_no=m.match_no,
                match_id=m.id if (m.team_home_id or m.team_away_id) else None,
                stage=m.stage,
                status=m.status,
                kickoff_utc=m.kickoff_utc,
                home=schemas.KnockoutSideOut(
                    team_id=m.team_home_id,
                    team=home_team.name if home_team else None,
                    score=m.score_home,
                    penalty=m.penalty_home,
                ),
                away=schemas.KnockoutSideOut(
                    team_id=m.team_away_id,
                    team=away_team.name if away_team else None,
                    score=m.score_away,
                    penalty=m.penalty_away,
                ),
                minute=m.minute,
                period=m.period,
                injury_time=m.injury_time,
            )
        )
    return schemas.KnockoutBracketOut(ties=ties)


@router.get("/odds", response_model=list[schemas.TournamentOddsOut])
def knockout_odds(db: Session = Depends(get_db)):
    """Every team's chance of reaching each knockout round and winning the title,
    from the full-tournament Monte-Carlo. Sorted by title probability."""
    cached = cache.get("knockout:odds")
    if cached is not None:
        return cached
    rows = db.query(TournamentOdds).all()
    out = []
    for r in rows:
        team = db.get(Team, r.team_id)
        out.append(
            schemas.TournamentOddsOut(
                team_id=r.team_id,
                team=team.name if team else "TBD",
                make_knockout=r.make_knockout,
                reach_r16=r.reach_r16,
                reach_qf=r.reach_qf,
                reach_sf=r.reach_sf,
                reach_final=r.reach_final,
                win_title=r.win_title,
            )
        )
    out.sort(key=lambda x: x.win_title or 0.0, reverse=True)
    cache.set("knockout:odds", out)
    return out
