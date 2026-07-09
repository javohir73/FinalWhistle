"""Snapshot writers are idempotent per (sport, day) and read serving tables."""
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    ProbabilitySnapshot, SportMatch, SportPrediction, SportTeam, Team, TournamentOdds,
)
from pipeline.prob_snapshots import snapshot_football, snapshot_nrl


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_snapshot_football_writes_odds_markets_idempotently():
    db = _session()
    team = Team(name="Australia", country_code="AUS")
    db.add(team); db.flush()
    db.add(TournamentOdds(team_id=team.id, make_knockout=0.34, win_title=0.02))
    db.commit()

    day = date(2026, 7, 9)
    assert snapshot_football(db, snapshot_date=day) == 2  # make_knockout + win_title
    assert snapshot_football(db, snapshot_date=day) == 2  # re-run same day: replaced, not duplicated
    assert db.query(ProbabilitySnapshot).filter_by(sport="football").count() == 2


def test_snapshot_nrl_snapshots_upcoming_round_win_probs():
    db = _session()
    home = SportTeam(sport="nrl", name="Broncos")
    away = SportTeam(sport="nrl", name="Storm")
    home2 = SportTeam(sport="nrl", name="Roosters")
    away2 = SportTeam(sport="nrl", name="Eels")
    db.add_all([home, away, home2, away2]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=19, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    # A later scheduled round -- must NOT be snapshotted; only the earliest
    # upcoming round (19) counts as "this round" for the movers feature.
    m2 = SportMatch(sport="nrl", season=2026, round=20, match_no=2,
                    home_team_id=home2.id, away_team_id=away2.id, status="scheduled")
    db.add_all([m, m2]); db.flush()
    db.add(SportPrediction(match_id=m.id, model_version="nrl-1",
                           p_home=0.39, p_draw=0.04, p_away=0.57))
    db.add(SportPrediction(match_id=m2.id, model_version="nrl-1",
                           p_home=0.51, p_draw=0.05, p_away=0.44))
    db.commit()

    n = snapshot_nrl(db, snapshot_date=date(2026, 7, 9))
    assert n == 2  # one win_match row per side, round-19 match only
    rows = db.query(ProbabilitySnapshot).filter_by(sport="nrl").all()
    assert {(r.entity_id, round(r.prob, 2)) for r in rows} == {(home.id, 0.39), (away.id, 0.57)}
    assert all(r.market == "win_match" and r.ref_id == m.id for r in rows)
