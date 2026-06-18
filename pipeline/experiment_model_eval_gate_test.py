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
