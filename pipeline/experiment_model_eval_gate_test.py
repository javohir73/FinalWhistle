"""Smoke test for the booster blend gate."""
from datetime import date

from pipeline.experiment_model_eval import run_blend_gate


def _rows():
    """Synthetic enriched rows: strong home edge → home win; spread across years so
    there is a pre-2018 train span, a tail, and 2018+ finals to test on."""
    rows = []
    for yr in range(2004, 2024):
        comp = "FIFA World Cup" if yr % 4 == 2 else "Friendly"
        for i in range(30):
            rows.append({
                "home_id": 1 + (i % 8), "away_id": 1 + ((i + 3) % 8),
                "pre_home": 1800.0, "pre_away": 1500.0, "is_neutral": True,
                "competition": comp, "score_home": 2, "score_away": 0,
                "date": date(yr, 6, 1 + (i % 20)),
            })
    return rows


def test_blend_gate_runs_and_reports_a_verdict():
    res = run_blend_gate(_rows(), train_lo=2004, tail_years=2, test_since=2018, n_boot=50)
    assert "delta_log_loss" in res
    assert "ll_ci" in res and len(res["ll_ci"]) == 2
    assert "weight" in res
    assert res["test_n"] > 0
    assert res["verdict"] in ("SHIP", "do-not-ship")


def test_gate_honors_served_params():
    """The booster must be scored against the engine actually served, not a
    hardcoded constant. Regression lock for the v0.1-vs-shipped-v0.2 bug: the
    gate's Poisson baseline must reflect the served params it is given. The rows
    are neutral-site favorites that always win, so a stronger elo→goals beta makes
    the favorite more confident and lowers the baseline log-loss."""
    from ml.models.params import ModelParams

    weak = ModelParams(version="weak", base=1.2, beta=0.0005,
                       home_adv=60.0, rho=-0.06, temperature=1.0)
    strong = ModelParams(version="strong", base=1.2, beta=0.0030,
                         home_adv=60.0, rho=-0.06, temperature=1.0)

    res_weak = run_blend_gate(_rows(), served_params=weak, n_boot=50)
    res_strong = run_blend_gate(_rows(), served_params=strong, n_boot=50)

    assert res_strong["base_log_loss"] < res_weak["base_log_loss"]


def test_wdl_and_grid_threads_eff_gap():
    from dataclasses import replace
    from pipeline.experiment_model_eval import wdl_and_grid
    from ml.models.params import load_params
    blob = {
        "method": "vector_scaling_segmented", "by": "effective_elo_gap",
        "buckets": {"0-50": {"t": 1.0, "b": [0.0, 1.0, 0.0]}},
        "default": {"t": 1.0, "b": [0.0, 0.0, 0.0]},
    }
    params = replace(load_params(), calibrator=blob)
    # Non-neutral so home_adv applies: 1450 vs 1500 + adv pulls eff gap into 0-50.
    # The 0-50 bucket lifts draws (b_draw=1.0), so it should be much higher.
    close, _ = wdl_and_grid(1450.0, 1500.0, False, params)
    # Neutral (adv 0): eff gap 50 -> outside 0-50 -> default identity (b_draw=0.0).
    far, _ = wdl_and_grid(1450.0, 1500.0, True, params)
    # With eff_gap threaded, close should have draw ~0.52, far should have draw ~0.29.
    assert close[1] > 0.5  # draw lifted significantly in 0-50 bucket
    assert far[1] < 0.3    # draw unchanged by default (identity)
    assert close[1] > far[1]  # close should have much higher draw
