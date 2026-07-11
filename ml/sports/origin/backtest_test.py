"""Origin walk-forward backtest + tuner, on synthetic histories."""
from datetime import datetime, timezone

import pytest

from ml.sports.nrl.model import NrlParams
from ml.sports.origin.backtest import load_backtest_record, tune, walk_forward


def _game(season, rnd, home_id, away_id, sh, sa, neutral=False):
    return {"home_id": home_id, "away_id": away_id, "score_home": sh,
            "score_away": sa, "neutral": neutral,
            "kickoff_utc": datetime(season, 5 + rnd, 1, tzinfo=timezone.utc)}


def _dominant_history(n_seasons=8, start=2000):
    """Team 0 always wins by 20 at home and away — a perfectly learnable signal."""
    hist = {}
    for i in range(n_seasons):
        s = start + i
        hist[s] = [
            _game(s, 1, 0, 1, 30, 10),
            _game(s, 2, 1, 0, 10, 30),
            _game(s, 3, 0, 1, 30, 10),
        ]
    return hist


def test_walk_forward_learns_dominant_team():
    out = walk_forward(_dominant_history(), NrlParams(), score_from=2003)
    assert out["n"] == 15  # 5 scored seasons x 3
    assert out["winner_accuracy"] == 1.0
    assert out["avg_log_loss"] < 0.69  # better than a coin flip
    assert out["span"] == [2003, 2007]
    assert isinstance(out["home_prior_log_loss"], float) and out["home_prior_log_loss"] > 0


def test_walk_forward_home_baseline_differs_from_model():
    # The dominant team wins even away, so always-pick-home is wrong 1/3 of the time.
    out = walk_forward(_dominant_history(), NrlParams(), score_from=2003)
    assert out["home_baseline_accuracy"] == pytest.approx(2 / 3)


def test_walk_forward_respects_neutral_flag():
    hist = {2000: [_game(2000, 1, 0, 1, 20, 20)]}  # single drawn game
    p = NrlParams(home_adv=100.0)
    scored = walk_forward(hist, p, score_from=2000)
    neutral_hist = {2000: [_game(2000, 1, 0, 1, 20, 20, neutral=True)]}
    scored_neutral = walk_forward(neutral_hist, p, score_from=2000)
    # With a draw outcome, log loss depends only on p_draw (same both runs),
    # but the baseline pick and brier differ through the home probability.
    assert scored["avg_brier"] != scored_neutral["avg_brier"]


def test_tune_returns_params_and_runs_on_tiny_grid():
    tuned = tune(_dominant_history(), val_from=2005,
                 grid={"k": [36.0], "home_adv": [30.0], "margin_mult_cap": [2.2],
                       "season_regress": [0.10], "p_draw": [0.02]})
    assert isinstance(tuned, NrlParams)
    assert tuned.k == 36.0 and tuned.version == "origin-elo-v0.1"


def test_load_backtest_record_missing_file_is_none(tmp_path, monkeypatch):
    import ml.sports.origin.backtest as bt
    monkeypatch.setattr(bt, "_RECORD_FILE", tmp_path / "backtest_record.json")
    assert load_backtest_record() is None
