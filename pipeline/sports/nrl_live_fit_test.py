from datetime import datetime, timedelta, timezone

import numpy as np

from app.models import SportMatch, SportPrediction
from ml.sports.nrl.live_params import NrlLiveParams
from pipeline.sports.nrl_live_fit import fit_from_db, generate_training_rows, simulate_score_trajectory


def test_simulate_score_trajectory_sums_to_final_score():
    rng = np.random.default_rng(1)
    traj = simulate_score_trajectory(24, rng)
    assert traj[-1][1] == 24
    assert all(traj[i][0] <= traj[i + 1][0] for i in range(len(traj) - 1))


def test_simulate_score_trajectory_zero_score_is_empty():
    rng = np.random.default_rng(1)
    assert simulate_score_trajectory(0, rng) == []


def test_generate_training_rows_labels_match_real_outcome():
    matches = [{"score_home": 24, "score_away": 10, "pregame_prob": 0.55}]
    rows = generate_training_rows(matches, trajectories_per_match=3, checkpoints_per_trajectory=4, seed=7)
    assert len(rows) == 3 * 4
    assert all(r["home_won"] is True for r in rows)
    assert all(0.0 <= r["minutes_remaining"] <= 80.0 for r in rows)


def test_fit_from_db_falls_back_to_defaults_with_too_few_matches(db_session):
    params = fit_from_db(db_session, version="nrl-live-v0.9")
    assert params == NrlLiveParams(version="nrl-live-v0.9")


def _add_finished_match_with_pregame_prediction(db_session, i, score_home, score_away):
    kickoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
    m = SportMatch(sport="nrl", season=2026, round=1, match_no=i, status="finished",
                    kickoff_utc=kickoff, score_home=score_home, score_away=score_away)
    db_session.add(m)
    db_session.flush()
    db_session.add(SportPrediction(match_id=m.id, model_version="nrl-elo-v0.1",
                                    p_home=0.6, p_draw=0.01, p_away=0.39,
                                    created_at=kickoff - timedelta(hours=1)))


def test_fit_from_db_uses_pre_kickoff_predictions_only(db_session):
    # Genuine class mix (home wins AND away wins) so the logistic actually fits.
    for i in range(25):
        if i % 2 == 0:
            _add_finished_match_with_pregame_prediction(db_session, i, 20 + i % 3, 10)
        else:
            _add_finished_match_with_pregame_prediction(db_session, i, 10, 20 + i % 3)
    db_session.commit()
    params = fit_from_db(db_session, trajectories_per_match=5, seed=3, version="nrl-live-v0.2")
    assert params.version == "nrl-live-v0.2"
    # Prove fitting happened: fitted coefficients differ from the hand-set
    # defaults, and being ahead on the scoreboard increases win probability.
    assert params != NrlLiveParams(version="nrl-live-v0.2")
    assert params.coef_score_diff > 0


def test_fit_from_db_falls_back_when_data_is_unfittable(db_session, caplog):
    # Every match is a home win -> single-class labels -> LogisticRegression
    # raises ValueError; fit_from_db keeps defaults but the caller's version.
    for i in range(25):
        _add_finished_match_with_pregame_prediction(db_session, i, 20 + i % 3, 10)
    db_session.commit()
    with caplog.at_level("WARNING"):
        params = fit_from_db(db_session, trajectories_per_match=5, seed=3, version="nrl-live-v0.2")
    assert params == NrlLiveParams(version="nrl-live-v0.2")
    assert any("failed to fit live model" in r.message for r in caplog.records)
