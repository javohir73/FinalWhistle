"""Tests for the Wave 1 finals-projections Monte Carlo
(pipeline/sports/nrl_projections.py)."""
import random
from datetime import datetime, timezone

from app.models import NrlProjection, SportMatch, SportTeam
from ml.sports.nrl.model import NrlParams
from pipeline.sports.nrl_projections import run, simulate

PARAMS = NrlParams()


def test_simulate_with_no_remaining_fixtures_is_deterministic():
    """No remaining matches -> every run ranks the SAME starting standings,
    so each team's top8/top4/minor_premiership must be exactly 0.0 or 1.0."""
    team_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    starting = {t: {"points": (10 - t) * 2, "diff": (10 - t) * 10} for t in team_ids}
    probs = simulate(team_ids, starting, remaining=[], elos={}, params=PARAMS, n_runs=50)

    # Team 1 has the most points -> always rank 1 -> minor premiers every run.
    assert probs[1]["minor_premiership"] == 1.0
    assert probs[1]["top8"] == 1.0
    assert probs[1]["top4"] == 1.0
    # Team 9 has the fewest points -> always last (rank 9) -> never top 8.
    assert probs[9]["top8"] == 0.0
    assert probs[9]["minor_premiership"] == 0.0


def test_simulate_heavy_favourite_wins_minor_premiership_almost_always():
    """With only 2 teams, top8/top4 are trivially 1.0 for both (any rank in a
    2-team field is <= 8 and <= 4) -- minor_premiership (rank == 1) is the
    only metric that's actually selective between exactly two candidates."""
    team_ids = [1, 2]
    starting = {1: {"points": 0, "diff": 0}, 2: {"points": 0, "diff": 0}}
    elos = {1: 1900.0, 2: 1100.0}  # enormous gap -> team 1 wins almost every sim
    remaining = [
        SportMatch(id=1, sport="nrl", season=2026, round=20, match_no=1,
                   home_team_id=1, away_team_id=2, status="scheduled")
    ]
    probs = simulate(team_ids, starting, remaining, elos, PARAMS,
                      n_runs=500, rng=random.Random(42))
    assert probs[1]["minor_premiership"] > 0.95
    assert probs[1]["top8"] == 1.0  # trivial in a 2-team field, sanity check only


def test_simulate_zero_runs_returns_zeroed_counts():
    probs = simulate([1, 2], {}, [], {}, PARAMS, n_runs=0)
    assert probs == {1: {"top8": 0, "top4": 0, "minor_premiership": 0},
                      2: {"top8": 0, "top4": 0, "minor_premiership": 0}}


def test_run_writes_and_replaces_projection_rows(db_session):
    a = SportTeam(sport="nrl", name="Storm")
    b = SportTeam(sport="nrl", name="Eels")
    db_session.add_all([a, b]); db_session.flush()
    db_session.add(SportMatch(sport="nrl", season=2026, round=1, match_no=1,
                              kickoff_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id,
                              status="finished", score_home=20, score_away=10))
    db_session.add(SportMatch(sport="nrl", season=2026, round=2, match_no=2,
                              kickoff_utc=datetime(2026, 3, 8, tzinfo=timezone.utc),
                              home_team_id=a.id, away_team_id=b.id, status="scheduled"))
    db_session.commit()

    n = run(db_session, season=2026, n_runs=25, rng=random.Random(1))
    assert n == 2
    rows = db_session.query(NrlProjection).all()
    assert {r.team for r in rows} == {"Storm", "Eels"}
    assert all(0.0 <= r.top8 <= 1.0 for r in rows)

    # Re-run must REPLACE, not accumulate.
    run(db_session, season=2026, n_runs=25, rng=random.Random(2))
    assert db_session.query(NrlProjection).count() == 2


def test_run_with_no_nrl_data_writes_nothing(db_session):
    assert run(db_session) == 0
