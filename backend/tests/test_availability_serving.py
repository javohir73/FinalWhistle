"""Serializer-level tests: PredictionOut carries the availability note when both
XIs are known, and None otherwise."""
from datetime import datetime, timezone

from app.models import LineupPlayer, Match, MatchLineup, Player, Prediction, Team
from app.serializers import prediction_to_out


def _match_pred(db):
    h, a = Team(name="France"), Team(name="Senegal")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True, status="scheduled",
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    pred = Prediction(match_id=m.id, model_version="v", prob_home_win=0.55,
                      prob_draw=0.27, prob_away_win=0.18, lambda_home=2.0,
                      lambda_away=1.0, rho=-0.1, confidence="Medium",
                      predicted_score_home=2, predicted_score_away=1,
                      predicted_score_prob=0.1, reasons=["a", "b", "c"], top_features=[])
    db.add(pred); db.commit()
    return m, h, a, pred


def _squad(db, team_id, star_pid):
    db.add(Player(provider_player_id=star_pid, name="Star", team_id=team_id, position="F",
                  club_goals=25, club_minutes=3000, wc_goals=3, wc_minutes=270))
    for i in range(11):
        db.add(Player(provider_player_id=star_pid * 100 + i, name=f"reg{i}", team_id=team_id,
                      position="M", club_goals=2, club_minutes=2400, wc_goals=0, wc_minutes=270))
    db.commit()


def _lineup(db, match_id, side, pids):
    ml = MatchLineup(match_id=match_id, side=side, provider="api_football",
                     fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.add(ml); db.commit()
    db.add_all([LineupPlayer(match_lineup_id=ml.id, name=f"pid{p}", is_starter=True,
                             order=i, provider_player_id=p) for i, p in enumerate(pids)])
    db.commit()


def test_prediction_out_has_availability_when_both_xi(db_session):
    m, h, a, pred = _match_pred(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    _lineup(db_session, m.id, "home", [100 + i for i in range(11)])   # 11 regulars, Star (1) benched
    _lineup(db_session, m.id, "away", [2] + [200 + i for i in range(10)])     # full strength
    out = prediction_to_out(db_session, m, pred)
    assert out.availability is not None
    assert out.availability.has_lineup is True
    home_block = next(t for t in out.availability.per_team if t.side == "home")
    assert home_block.attack_delta_pct < 0.0
    assert "Star" in home_block.note
    # The published triple is unchanged by availability.
    assert out.probabilities.home_win == 0.55


def test_prediction_out_availability_none_without_xi(db_session):
    m, h, a, pred = _match_pred(db_session)
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    out = prediction_to_out(db_session, m, pred)
    assert out.availability is None


def test_injury_note_names_player_and_reason(db_session):
    m, h, a, pred = _match_pred(db_session)   # helper from this file
    _squad(db_session, h.id, 1); _squad(db_session, a.id, 2)
    m.injuries = [{"provider_player_id": 1, "name": "Star", "type": "out",
                   "reason": "Calf Injury", "side": "home"}]
    db_session.commit()
    out = prediction_to_out(db_session, m, pred)
    assert out.availability is not None
    home = next(t for t in out.availability.per_team if t.side == "home")
    assert "Star" in home.note and "Calf Injury" in home.note
    assert home.attack_delta_pct < 0.0
    assert out.probabilities.home_win == 0.55   # published number unchanged
