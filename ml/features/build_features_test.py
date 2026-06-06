"""Tests for feature engineering + cold-start fallbacks (task 3.4)."""
from datetime import datetime, timezone

from app.models import HistoricalMatch, Team, TeamStats
from ml.features.build_features import (
    build_match_features,
    estimate_strength,
    head_to_head,
)


def test_strength_uses_elo_when_present():
    t = Team(name="X", elo_rating=1900.0)
    strength, source = estimate_strength(t)
    assert strength == 1900.0 and source == "elo"


def test_strength_falls_back_to_fifa_rank():
    t = Team(name="X", elo_rating=None, fifa_rank=1)
    strength, source = estimate_strength(t)
    assert source == "fifa_rank" and strength > 1800


def test_strength_falls_back_to_confederation():
    t = Team(name="X", elo_rating=None, fifa_rank=None, confederation="UEFA")
    strength, source = estimate_strength(t)
    assert source == "confederation" and strength == 1750.0


def test_strength_global_default_last_resort():
    t = Team(name="X")
    strength, source = estimate_strength(t)
    assert source == "default" and strength == 1500.0


def test_head_to_head_counts(db_session):
    a, b = Team(name="A"), Team(name="B")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add_all([
        HistoricalMatch(date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        team_a_id=a.id, team_b_id=b.id, score_a=2, score_b=1),
        HistoricalMatch(date=datetime(2023, 1, 1, tzinfo=timezone.utc),
                        team_a_id=b.id, team_b_id=a.id, score_a=0, score_b=0),
    ])
    db_session.commit()
    h2h = head_to_head(db_session, a.id, b.id)
    assert h2h["matches"] == 2
    assert h2h["a_wins"] == 1 and h2h["draws"] == 1 and h2h["b_wins"] == 0


def test_build_features_full(db_session):
    home = Team(name="Home", elo_rating=2000.0)
    away = Team(name="Away", elo_rating=1700.0)
    db_session.add_all([home, away])
    db_session.flush()
    db_session.add(TeamStats(
        team_id=home.id, as_of_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        matches_played=10, goals_for=20, goals_against=5, form_points_last10=24.0,
    ))
    db_session.commit()

    f = build_match_features(db_session, home, away, host_team_id=home.id)
    assert f.elo_diff == 300.0
    assert f.is_home_host is True
    assert f.form_home == 24.0
    assert f.goals_for_avg_home == 2.0
    assert f.data_points_home == 10 and f.data_points_away == 0
