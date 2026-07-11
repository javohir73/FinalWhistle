"""Round-trip tests for Wave 1's schema additions: three new columns on
sport_predictions (predicted_margin, predicted_total, preview_text) and the
nrl_projections table. Uses the same local in-memory SQLite pattern as
backend/tests/test_sports_api.py -- Base.metadata.create_all picks up the
model changes directly, so these tests fail until app/models/__init__.py is
updated (no alembic run needed for SQLite-backed tests)."""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import NrlProjection, SportMatch, SportPrediction, SportTeam


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_sport_prediction_round_trips_margin_total_preview():
    db = _session()
    home = SportTeam(sport="nrl", name="Storm")
    away = SportTeam(sport="nrl", name="Eels")
    db.add_all([home, away]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()

    pred = SportPrediction(
        match_id=m.id, model_version="nrl-elo-v0.1",
        p_home=0.6, p_draw=0.01, p_away=0.39, expected_margin=3.0,
        predicted_margin=4.2, predicted_total=41.5,
        preview_text="Storm are the model's pick.",
    )
    db.add(pred); db.commit()

    reloaded = db.query(SportPrediction).one()
    assert reloaded.predicted_margin == 4.2
    assert reloaded.predicted_total == 41.5
    assert reloaded.preview_text == "Storm are the model's pick."


def test_sport_prediction_new_columns_are_nullable():
    db = _session()
    home = SportTeam(sport="nrl", name="Storm")
    away = SportTeam(sport="nrl", name="Eels")
    db.add_all([home, away]); db.flush()
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                   home_team_id=home.id, away_team_id=away.id, status="scheduled")
    db.add(m); db.flush()

    pred = SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                            p_home=0.5, p_draw=0.01, p_away=0.49, expected_margin=0.0)
    db.add(pred); db.commit()

    reloaded = db.query(SportPrediction).one()
    assert reloaded.predicted_margin is None
    assert reloaded.predicted_total is None
    assert reloaded.preview_text is None


def test_nrl_projection_round_trips():
    db = _session()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    db.add(NrlProjection(team="Storm", top8=0.91, top4=0.42, minor_premiership=0.05,
                          computed_at=now))
    db.commit()

    row = db.query(NrlProjection).one()
    assert row.team == "Storm"
    assert row.top8 == 0.91
    assert row.top4 == 0.42
    assert row.minor_premiership == 0.05
    # SQLite's DateTime(timezone=True) round-trips as a naive datetime (this
    # is a dialect-wide quirk -- every existing DateTime(timezone=True)
    # column in this repo, e.g. Odds.captured_at, behaves the same way under
    # pysqlite/SQLAlchemy 2.0.36), so re-attach UTC before comparing.
    assert row.computed_at.replace(tzinfo=timezone.utc) == now
