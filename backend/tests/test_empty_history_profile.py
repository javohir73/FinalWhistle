"""A club with no matches in the scoped competition must get NO verdicts.

The averages behind strengths/weaknesses divided by `len(rows) or 1`, so an
empty ledger scored 0 on every axis and satisfied three thresholds at once:
"Solid defense" (0 conceded) beside "Poor recent form" and "Struggles to score"
(0 won, 0 scored). Three confident judgements about a club the platform has
never seen play. Cross-border qualifying rounds make that routine.
"""
from datetime import datetime, timezone

from app import serializers
from app.models import HistoricalMatch, Team

UCL = "UEFA Champions League"


def _team(db, name, elo=1500.0):
    t = Team(name=name, elo_rating=elo)
    db.add(t)
    db.flush()
    return t


def test_no_scoped_history_yields_no_verdicts(db_session):
    team = _team(db_session, "Debutant FC")
    db_session.commit()

    out = serializers.team_profile(db_session, team, history_competition=UCL)

    assert out.recent_form == []
    assert out.strengths == []
    assert out.weaknesses == []


def test_history_in_another_competition_does_not_leak_verdicts(db_session):
    """Scoping is the point: domestic form must not describe a UCL profile."""
    team = _team(db_session, "Domestic Only")
    opp = _team(db_session, "Someone Else")
    for day in (1, 2, 3):
        db_session.add(HistoricalMatch(
            date=datetime(2026, 3, day, tzinfo=timezone.utc),
            team_a_id=team.id, team_b_id=opp.id, score_a=4, score_b=0,
            competition="Premier League", is_neutral=False,
        ))
    db_session.commit()

    out = serializers.team_profile(db_session, team, history_competition=UCL)
    assert out.strengths == [] and out.weaknesses == []
    # Unscoped, the same club is described normally.
    unscoped = serializers.team_profile(db_session, team, history_competition=None)
    assert unscoped.strengths, "a club WITH history should still get verdicts"


def test_real_history_still_produces_verdicts(db_session):
    """The guard must not mute clubs that do have a record."""
    team = _team(db_session, "Prolific FC")
    opp = _team(db_session, "Whipping Boys")
    for day in (1, 2, 3, 4):
        db_session.add(HistoricalMatch(
            date=datetime(2026, 3, day, tzinfo=timezone.utc),
            team_a_id=team.id, team_b_id=opp.id, score_a=3, score_b=0,
            competition=UCL, is_neutral=False,
        ))
    db_session.commit()

    out = serializers.team_profile(db_session, team, history_competition=UCL)
    assert len(out.recent_form) == 4
    assert "Strong recent form" in out.strengths
    assert "Potent attack" in out.strengths
    assert "Solid defense" in out.strengths
    assert out.weaknesses == ["No glaring weakness"]


def test_a_single_clean_sheet_is_not_reported_as_no_record(db_session):
    """One match is thin, but it IS a record — the empty-guard must not eat it."""
    team = _team(db_session, "One Gamer")
    opp = _team(db_session, "Opponent")
    db_session.add(HistoricalMatch(
        date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        team_a_id=team.id, team_b_id=opp.id, score_a=0, score_b=0,
        competition=UCL, is_neutral=False,
    ))
    db_session.commit()

    out = serializers.team_profile(db_session, team, history_competition=UCL)
    assert len(out.recent_form) == 1
    assert out.strengths or out.weaknesses
