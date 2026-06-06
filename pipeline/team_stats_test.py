"""Tests for team_stats computation (task 2.10)."""
from datetime import datetime, timezone

from app.models import HistoricalMatch, Team, TeamStats
from pipeline.team_stats import compute_team_stats


def _seed_two_teams_with_matches(db):
    a, b = Team(name="Alpha"), Team(name="Beta")
    db.add_all([a, b])
    db.flush()
    # Alpha beats Beta 2-0, then draws 1-1.
    db.add_all(
        [
            HistoricalMatch(
                date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                team_a_id=a.id, team_b_id=b.id, score_a=2, score_b=0,
                competition="Friendly", is_neutral=True,
            ),
            HistoricalMatch(
                date=datetime(2025, 6, 1, tzinfo=timezone.utc),
                team_a_id=a.id, team_b_id=b.id, score_a=1, score_b=1,
                competition="Friendly", is_neutral=True,
            ),
        ]
    )
    db.commit()
    return a, b


def test_computes_form_and_goals(db_session):
    a, b = _seed_two_teams_with_matches(db_session)
    summary = compute_team_stats(db_session, as_of=datetime(2025, 12, 1, tzinfo=timezone.utc))
    assert summary["teams_with_stats"] == 2

    sa = db_session.query(TeamStats).filter_by(team_id=a.id).one()
    assert sa.matches_played == 2
    assert sa.goals_for == 3 and sa.goals_against == 1
    assert sa.form_points_last10 == 4.0  # win (3) + draw (1)
    assert sa.clean_sheets == 1

    sb = db_session.query(TeamStats).filter_by(team_id=b.id).one()
    assert sb.form_points_last10 == 1.0  # loss (0) + draw (1)


def test_idempotent_per_as_of(db_session):
    _seed_two_teams_with_matches(db_session)
    as_of = datetime(2025, 12, 1, tzinfo=timezone.utc)
    compute_team_stats(db_session, as_of=as_of)
    compute_team_stats(db_session, as_of=as_of)
    # one row per (team, as_of), not duplicated
    assert db_session.query(TeamStats).count() == 2
