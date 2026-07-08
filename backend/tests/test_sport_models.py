"""sport_* tables (multi-sport vertical, NRL first): storage for teams,
matches, predictions and evaluated results, scoped by a `sport` column so
NFL/NBA can share the same tables later. Mirrors the football Team/Match/
Prediction/PredictionResult shape but kept separate — see task-1-brief.md."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base


def _make_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def client():
    TestingSession = _make_session()
    yield None, TestingSession


def test_sport_tables_round_trip(client):
    _, TestingSession = client
    db = TestingSession()
    from app.models import SportMatch, SportPrediction, SportTeam

    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db.add_all([a, b])
    db.flush()
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=3,
                   kickoff_utc=datetime(2026, 3, 5, 9, tzinfo=timezone.utc),
                   venue="AAMI Park", home_team_id=a.id, away_team_id=b.id,
                   score_home=52, score_away=4, status="finished")
    db.add(m)
    db.flush()
    p = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                        p_home=0.71, p_draw=0.01, p_away=0.28,
                        expected_margin=8.5)
    db.add(p)
    db.commit()
    assert db.get(SportPrediction, p.id).is_shadow is True
    assert db.get(SportMatch, m.id).status == "finished"


def test_sport_team_unique_per_sport(client):
    _, TestingSession = client
    db = TestingSession()
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.models import SportTeam

    db.add_all([SportTeam(sport="nrl", name="Storm"),
                SportTeam(sport="nfl", name="Storm")])
    db.commit()  # same name, different sport: fine
    db.add(SportTeam(sport="nrl", name="Storm"))
    with pytest.raises(IntegrityError):
        db.commit()
