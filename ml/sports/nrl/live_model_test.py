import math

from ml.sports.nrl.live_model import LiveWinProbModel, _features, predict_live_prob
from ml.sports.nrl.live_params import NrlLiveParams


def test_features_shape_and_interaction_term():
    x = _features(score_diff=6.0, minutes_remaining=40.0, pregame_prob=0.6)
    assert x[0] == 6.0
    assert x[1] == 6.0 * math.sqrt(40.0)
    assert x[2] == math.log(0.6 / 0.4)


def test_fit_recovers_a_monotonic_relationship():
    rows = []
    for score_diff in range(-20, 21, 2):
        rows.append({"score_diff": float(score_diff), "minutes_remaining": 5.0,
                      "pregame_prob": 0.5, "home_won": score_diff > 0})
    model = LiveWinProbModel().fit(rows)
    p_ahead = model.predict_proba(score_diff=12.0, minutes_remaining=5.0, pregame_prob=0.5)
    p_behind = model.predict_proba(score_diff=-12.0, minutes_remaining=5.0, pregame_prob=0.5)
    assert p_ahead > 0.5 > p_behind


def test_predict_live_prob_pure_math_matches_sigmoid_by_hand():
    params = NrlLiveParams(version="test", intercept=0.1, coef_score_diff=0.2,
                            coef_interaction=0.01, coef_pregame_logit=0.5)
    got = predict_live_prob(score_diff=4.0, minutes_remaining=20.0, pregame_prob=0.6, params=params)
    x = _features(4.0, 20.0, 0.6)
    z = 0.1 + 0.2 * x[0] + 0.01 * x[1] + 0.5 * x[2]
    expected = 1.0 / (1.0 + math.exp(-z))
    assert abs(got - expected) < 1e-9


def test_load_nrl_live_params_falls_back_to_defaults(tmp_path, monkeypatch):
    import ml.sports.nrl.live_params as live_params
    monkeypatch.setattr(live_params, "_PARAMS_FILE", tmp_path / "missing.json")
    params = live_params.load_nrl_live_params()
    assert params == NrlLiveParams()


def test_save_then_load_nrl_live_params_round_trips(tmp_path, monkeypatch):
    import ml.sports.nrl.live_params as live_params
    monkeypatch.setattr(live_params, "_PARAMS_FILE", tmp_path / "live_params.json")
    written = NrlLiveParams(version="nrl-live-v0.2", intercept=0.3, coef_score_diff=0.22,
                             coef_interaction=0.015, coef_pregame_logit=0.48)
    live_params.save_nrl_live_params(written)
    assert live_params.load_nrl_live_params() == written
