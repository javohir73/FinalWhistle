import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NrlLiveEvent, NrlLiveState, NrlTeamList, SportMatch


def _make_match(db):
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=1, status="scheduled")
    db.add(m)
    db.flush()
    return m


def test_nrl_team_list_unique_match_team_jersey(db_session):
    m = _make_match(db_session)
    db_session.add(NrlTeamList(match_id=m.id, team="Broncos", jersey=1, player="A. Test", position="FB"))
    db_session.commit()
    db_session.add(NrlTeamList(match_id=m.id, team="Broncos", jersey=1, player="B. Test", position="FB"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_nrl_team_list_default_is_late_change_false(db_session):
    m = _make_match(db_session)
    row = NrlTeamList(match_id=m.id, team="Broncos", jersey=1, player="A. Test", position="FB")
    db_session.add(row)
    db_session.commit()
    assert row.is_late_change is False


def test_nrl_live_state_one_row_per_match(db_session):
    m = _make_match(db_session)
    db_session.add(NrlLiveState(match_id=m.id, status="live", minute=10,
                                 score_home=6, score_away=0, live_home_prob=0.7))
    db_session.commit()
    db_session.add(NrlLiveState(match_id=m.id, status="live", minute=20,
                                 score_home=12, score_away=0, live_home_prob=0.8))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_nrl_live_event_round_trips(db_session):
    m = _make_match(db_session)
    ev = NrlLiveEvent(match_id=m.id, minute=5, type="score", team="home",
                       player=None, prob_after=0.62)
    db_session.add(ev)
    db_session.commit()
    assert ev.id is not None
