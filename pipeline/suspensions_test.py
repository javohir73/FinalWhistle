"""Tests for the suspension signal (red cards, yellow accumulation, keeper shift)."""
from datetime import datetime, timedelta

from app.models import Match
from pipeline.ingest.wc26_structure import load_structure
from pipeline.suspensions import keeper_pk_shift, suspension_statuses

T0 = datetime(2026, 6, 20, 18, 0)


def _squad():
    return [
        {"provider_player_id": 1, "name": "Erling Haaland", "position": "F",
         "club_goals": 30, "club_minutes": 2700, "wc_goals": 3, "wc_minutes": 450},
        {"provider_player_id": 2, "name": "Martin Odegaard", "position": "M",
         "club_goals": 10, "club_minutes": 2500, "wc_goals": 1, "wc_minutes": 450},
        {"provider_player_id": 3, "name": "Orjan Nyland", "position": "G",
         "club_goals": 0, "club_minutes": 2600, "wc_goals": 0, "wc_minutes": 450},
    ]


def _matches_for(db, team_id, n):
    """n structure matches rigged as this team's schedule, kickoffs a day apart."""
    ms = db.query(Match).order_by(Match.id).limit(n).all()
    for i, m in enumerate(ms):
        m.team_home_id = team_id
        m.team_away_id = 999_000 + i  # synthetic FK values are fine in sqlite tests
        m.kickoff_utc = T0 + timedelta(days=i)
        m.status = "finished" if i < n - 1 else "scheduled"
        m.stage = "group"
        m.card_events = []
    db.commit()
    return ms


def test_red_card_last_match_bans_for_next(db_session):
    load_structure(db_session)
    m1, m2 = _matches_for(db_session, 501, 2)
    m1.card_events = [{"minute": 88, "side": "home", "player": "Erling Haaland", "type": "red"}]
    db_session.commit()
    statuses = suspension_statuses(db_session, m2, "home", _squad())
    assert statuses == {1: {"status": "out", "reason": "suspended — red card last match"}}


def test_yellow_accumulation_across_matches_bans(db_session):
    load_structure(db_session)
    m1, m2, m3 = _matches_for(db_session, 501, 3)
    m1.card_events = [{"minute": 30, "side": "home", "player": "Martin Odegaard", "type": "yellow"}]
    m2.card_events = [{"minute": 60, "side": "home", "player": "Martin Odegaard", "type": "yellow"}]
    db_session.commit()
    statuses = suspension_statuses(db_session, m3, "home", _squad())
    assert statuses == {2: {"status": "out", "reason": "suspended — yellow-card accumulation"}}


def test_served_ban_stays_clear(db_session):
    # Both yellows came before the LAST match -> the ban was served there.
    load_structure(db_session)
    m1, m2, m3 = _matches_for(db_session, 501, 3)
    m1.card_events = [
        {"minute": 30, "side": "home", "player": "Martin Odegaard", "type": "yellow"},
        {"minute": 75, "side": "home", "player": "Martin Odegaard", "type": "yellow"},
    ]
    db_session.commit()
    assert suspension_statuses(db_session, m3, "home", _squad()) == {}


def test_yellow_wipe_after_quarter_finals(db_session):
    # A yellow in the group stage + one in the QF would ban for the SF — but
    # the slate is wiped after the QF, so accumulation cannot reach the SF.
    load_structure(db_session)
    m1, m2, m3 = _matches_for(db_session, 501, 3)
    m1.stage, m2.stage, m3.stage = "group", "QF", "SF"
    m1.card_events = [{"minute": 10, "side": "home", "player": "Martin Odegaard", "type": "yellow"}]
    m2.card_events = [{"minute": 20, "side": "home", "player": "Martin Odegaard", "type": "yellow"}]
    db_session.commit()
    assert suspension_statuses(db_session, m3, "home", _squad()) == {}
    # A red in the QF still bans for the SF — the wipe is yellows-only.
    m2.card_events = [{"minute": 20, "side": "home", "player": "Erling Haaland", "type": "red"}]
    db_session.commit()
    assert 1 in suspension_statuses(db_session, m3, "home", _squad())


def test_unmatched_card_name_cannot_invent_a_ban(db_session):
    load_structure(db_session)
    m1, m2 = _matches_for(db_session, 501, 2)
    m1.card_events = [{"minute": 88, "side": "home", "player": "Totally Unknown", "type": "red"}]
    db_session.commit()
    assert suspension_statuses(db_session, m2, "home", _squad()) == {}


def test_no_prior_match_means_no_suspensions(db_session):
    load_structure(db_session)
    (m1,) = _matches_for(db_session, 501, 1)
    assert suspension_statuses(db_session, m1, "home", _squad()) == {}


def test_keeper_pk_shift_signs_and_neutrality():
    squads = {"home": _squad(), "away": _squad()}
    gk_out = {3: {"status": "out", "reason": "suspended"}}
    assert keeper_pk_shift(squads, {"home": gk_out, "away": {}}, 0.03) == -0.03
    assert keeper_pk_shift(squads, {"home": {}, "away": gk_out}, 0.03) == 0.03
    assert keeper_pk_shift(squads, {"home": gk_out, "away": gk_out}, 0.03) == 0.0
    assert keeper_pk_shift(squads, {"home": gk_out, "away": {}}, 0.0) == 0.0
    # An outfield player out is not a keeper signal.
    field_out = {1: {"status": "out", "reason": "suspended"}}
    assert keeper_pk_shift(squads, {"home": field_out, "away": {}}, 0.03) == 0.0
