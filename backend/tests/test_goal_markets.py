from app import serializers
from app.models import Match, Prediction, Team


def _setup(db):
    h, a = Team(name="Argentina"), Team(name="Cape Verde")
    db.add_all([h, a]); db.commit()
    m = Match(tournament_id=1, stage="group", is_neutral=True,
              team_home_id=h.id, team_away_id=a.id)
    db.add(m); db.commit()
    p = Prediction(match_id=m.id, model_version="v",
                   prob_home_win=0.7, prob_draw=0.2, prob_away_win=0.1,
                   lambda_home=2.5, lambda_away=0.4, rho=-0.1)
    db.add(p); db.commit()
    return m, p


def test_prediction_out_includes_goal_markets(db_session):
    m, p = _setup(db_session)
    out = serializers.prediction_to_out(db_session, m, p)
    assert out.goal_markets is not None
    gm = out.goal_markets
    assert 0.0 <= gm.btts <= 1.0
    assert gm.home.to_score >= gm.home.p2 >= gm.home.p3 >= gm.home.p4
    assert gm.total.over_1_5 >= gm.total.over_2_5 >= gm.total.over_3_5


def test_goal_markets_null_when_rates_missing(db_session):
    m, p = _setup(db_session)
    p.lambda_home = None
    db_session.commit()
    out = serializers.prediction_to_out(db_session, m, p)
    assert out.goal_markets is None
