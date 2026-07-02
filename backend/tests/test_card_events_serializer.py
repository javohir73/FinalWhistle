"""Card events on the match summary: exposure + live-model count threading."""
from app.models import Match, Prediction, Team
from app.serializers import _card_counts, match_to_summary
from pipeline.ingest.wc26_structure import load_structure


def _match(db_session) -> Match:
    load_structure(db_session)
    h = db_session.query(Team).filter_by(name="Mexico").one()
    a = db_session.query(Team).filter_by(name="South Africa").one()
    return db_session.query(Match).filter_by(team_home_id=h.id, team_away_id=a.id).one()


def test_card_counts_reds_and_active_yellows():
    events = [
        {"minute": 20, "side": "home", "player": "A", "type": "yellow"},
        {"minute": 50, "side": "home", "player": "A", "type": "red"},   # second yellow
        {"minute": 60, "side": "home", "player": "B", "type": "yellow"},
        {"minute": 70, "side": "away", "player": "C", "type": "red"},
    ]
    # A's booking is consumed by the sending-off: only B's yellow stays active.
    assert _card_counts(events) == {
        "red_home": 1, "red_away": 1, "yellow_home": 1, "yellow_away": 0}


def test_card_counts_none_and_malformed_are_zero():
    zero = {"red_home": 0, "red_away": 0, "yellow_home": 0, "yellow_away": 0}
    assert _card_counts(None) == zero
    assert _card_counts(["garbage", {"type": "red", "side": "bench"}]) == zero


def test_summary_exposes_card_events_and_red_moves_live_bar(db_session):
    m = _match(db_session)
    m.status = "in_play"
    m.score_home, m.score_away = 0, 0
    m.minute, m.period = 30, "first_half"
    db_session.add(Prediction(
        match_id=m.id, model_version="test",
        prob_home_win=0.5, prob_draw=0.3, prob_away_win=0.2,
        lambda_home=1.4, lambda_away=1.0, rho=-0.06,
    ))
    db_session.commit()
    base = match_to_summary(db_session, m).live_probabilities
    assert base is not None

    m.card_events = [
        {"minute": 25, "side": "home", "player": "J. Vasquez", "type": "red"}]
    db_session.commit()
    out = match_to_summary(db_session, m)
    assert out.card_events[0].player == "J. Vasquez"
    assert out.card_events[0].type == "red"
    assert out.live_probabilities.home_win < base.home_win


def test_summary_card_events_default_empty(db_session):
    out = match_to_summary(db_session, _match(db_session))
    assert out.card_events == []
