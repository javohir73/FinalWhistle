"""Tests for the closing-line benchmark (ml/evaluation/market_benchmark.py)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from ml.evaluation.market_benchmark import (
    MatchedMatch,
    benchmark,
    benchmark_binary,
    devig,
    devig2,
    format_report,
    join_odds_to_rows,
    ou25_label,
    result_to_json,
)


# --- devig ---------------------------------------------------------------

def test_devig_sums_to_one_and_orders_correctly():
    p = devig(1.60, 4.20, 6.00)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[1] > p[2]  # shortest price -> highest probability


def test_devig_removes_margin_proportionally():
    # Fair odds 2/4/4 imply exactly 0.5/0.25/0.25 once normalized.
    assert devig(2.0, 4.0, 4.0) == pytest.approx((0.5, 0.25, 0.25))


def test_devig_rejects_bad_odds():
    with pytest.raises(ValueError):
        devig(1.0, 3.0, 4.0)


# --- join ----------------------------------------------------------------

def _row(home_id, away_id, d, sh, sa, probs):
    return {
        "home_id": home_id, "away_id": away_id,
        "date": datetime(d.year, d.month, d.day),
        "score_home": sh, "score_away": sa, "model_probs": probs,
    }


_NAMES = {1: "France", 2: "Croatia"}
_ODDS = {
    "date": date(2018, 7, 15), "home_team": "France", "away_team": "Croatia",
    "odds_home": 2.0, "odds_draw": 4.0, "odds_away": 4.0,
}


def test_join_matches_by_date_and_names():
    rows = [_row(1, 2, date(2018, 7, 15), 4, 2, (0.5, 0.3, 0.2))]
    matched, unmatched = join_odds_to_rows(rows, [_ODDS], _NAMES)
    assert not unmatched
    assert matched[0].label == "H"
    assert matched[0].market_probs == pytest.approx((0.5, 0.25, 0.25))


def test_join_swapped_orientation_flips_market_probs():
    rows = [_row(2, 1, date(2018, 7, 15), 2, 4, (0.2, 0.3, 0.5))]  # Croatia listed home
    matched, _ = join_odds_to_rows(rows, [_ODDS], _NAMES)
    # Odds row says France home @ 0.5 -> as away side here it must be 0.5.
    assert matched[0].market_probs == pytest.approx((0.25, 0.25, 0.5))
    assert matched[0].label == "A"


def test_join_applies_normalizer():
    odds = dict(_ODDS, home_team="FRANCE ", away_team=" croatia")
    rows = [_row(1, 2, date(2018, 7, 15), 0, 0, (0.4, 0.3, 0.3))]
    matched, _ = join_odds_to_rows(
        rows, [odds], _NAMES, normalize=lambda s: s.strip().lower()
    )
    assert len(matched) == 1
    assert matched[0].label == "D"


def test_join_reports_unmatched():
    rows = [_row(1, 2, date(2022, 12, 18), 3, 3, (0.4, 0.3, 0.3))]  # date mismatch
    matched, unmatched = join_odds_to_rows(rows, [_ODDS], _NAMES)
    assert not matched and len(unmatched) == 1


# --- benchmark -----------------------------------------------------------

def _mm(model, market, label):
    return MatchedMatch(
        date=date(2026, 6, 15), home="A", away="B",
        model_probs=model, market_probs=market, label=label,
    )


def test_identical_predictors_show_no_difference():
    p = (0.5, 0.3, 0.2)
    r = benchmark([_mm(p, p, "H"), _mm(p, p, "D")], n_bootstrap=200)
    assert r["diff_log_loss"] == pytest.approx(0.0)
    assert r["mean_edge"] == pytest.approx(0.0)
    assert r["model_win_rate"] == 0.0  # never strictly better
    assert r["diff_ci95"][0] <= 0.0 <= r["diff_ci95"][1]


def test_sharper_model_beats_market():
    # Model confident about the realized outcome, market lukewarm.
    matched = [_mm((0.8, 0.1, 0.1), (0.4, 0.3, 0.3), "H")] * 10
    r = benchmark(matched, n_bootstrap=200)
    assert r["diff_log_loss"] < 0
    assert r["model_win_rate"] == 1.0
    assert r["mean_edge"] == pytest.approx(0.4)
    assert "MODEL BEATS MARKET" in format_report(r, "t")


def test_overconfident_wrong_model_loses():
    matched = [_mm((0.8, 0.1, 0.1), (0.4, 0.3, 0.3), "A")] * 10
    r = benchmark(matched, n_bootstrap=200)
    assert r["diff_log_loss"] > 0
    assert "MARKET BEATS MODEL" in format_report(r, "t")


def test_empty_input_raises():
    with pytest.raises(ValueError):
        benchmark([])


def test_report_contains_headline_numbers():
    p, q = (0.5, 0.3, 0.2), (0.45, 0.3, 0.25)
    out = format_report(benchmark([_mm(p, q, "H")] * 5, n_bootstrap=100), "sample")
    assert "sample (5 matches)" in out
    assert "log-loss" in out and "verdict:" in out


# --- result_to_json ------------------------------------------------------

def test_result_to_json_shape_and_rounding():
    matched = [_mm((0.8, 0.1, 0.1), (0.4, 0.3, 0.3), "H")] * 10
    result = benchmark(matched, n_bootstrap=200)
    js = result_to_json(result, "WC26 live", "2026-07-03T00:00:00+00:00")
    assert js["status"] == "ready"
    assert js["dataset"] == "WC26 live"
    assert js["updated_at"] == "2026-07-03T00:00:00+00:00"
    assert js["n_matches"] == result["n_matches"]
    assert js["model"] == result["model"]
    assert js["market"] == result["market"]
    assert js["diff_log_loss"] == round(result["diff_log_loss"], 4)
    lo, hi = result["diff_ci95"]
    assert js["diff_ci95"] == [round(lo, 4), round(hi, 4)]
    assert js["model_win_rate"] == round(result["model_win_rate"], 4)
    assert js["mean_edge"] == round(result["mean_edge"], 4)


def test_result_to_json_verdict_matches_format_report():
    # Sharper model -> MODEL BEATS MARKET, and both surfaces must agree.
    matched = [_mm((0.8, 0.1, 0.1), (0.4, 0.3, 0.3), "H")] * 10
    result = benchmark(matched, n_bootstrap=200)
    js = result_to_json(result, "t", "2026-07-03T00:00:00+00:00")
    assert js["verdict"] == "MODEL BEATS MARKET (credible: CI fully below 0)"
    assert js["verdict"] in format_report(result, "t")


def test_result_to_json_verdict_market_beats_model():
    matched = [_mm((0.8, 0.1, 0.1), (0.4, 0.3, 0.3), "A")] * 10
    result = benchmark(matched, n_bootstrap=200)
    js = result_to_json(result, "t", "2026-07-03T00:00:00+00:00")
    assert js["verdict"] == "MARKET BEATS MODEL (credible: CI fully above 0)"
    assert js["verdict"] in format_report(result, "t")


def test_result_to_json_verdict_no_credible_difference():
    p = (0.5, 0.3, 0.2)
    result = benchmark([_mm(p, p, "H"), _mm(p, p, "D")], n_bootstrap=200)
    js = result_to_json(result, "t", "2026-07-03T00:00:00+00:00")
    assert js["verdict"] == "NO CREDIBLE DIFFERENCE (CI straddles 0)"
    assert js["verdict"] in format_report(result, "t")


# --- devig2 (2-way) ------------------------------------------------------

def test_devig2_fair_coin_is_half_half():
    assert devig2(2.0, 2.0) == pytest.approx((0.5, 0.5))


def test_devig2_sums_to_one_and_shorter_price_is_higher():
    p = devig2(1.5, 3.0)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[1]  # shorter price -> higher probability


def test_devig2_rejects_bad_odds():
    with pytest.raises(ValueError):
        devig2(1.0, 3.0)
    with pytest.raises(ValueError):
        devig2(3.0, 1.0)


# --- benchmark_binary ----------------------------------------------------

def test_benchmark_binary_identical_predictors_show_no_difference():
    model_p = [0.6, 0.4, 0.7]
    r = benchmark_binary(model_p, list(model_p), [1, 0, 1], n_bootstrap=200)
    assert r["n_matches"] == 3
    assert r["diff_log_loss"] == pytest.approx(0.0)
    assert r["mean_edge"] == pytest.approx(0.0)
    assert r["model_win_rate"] == 0.0  # never strictly better
    assert r["diff_ci95"][0] <= 0.0 <= r["diff_ci95"][1]


def test_benchmark_binary_has_same_shape_as_benchmark():
    r = benchmark_binary([0.8] * 5, [0.5] * 5, [1] * 5, n_bootstrap=100)
    assert set(r) == {
        "n_matches", "model", "market", "diff_log_loss",
        "diff_ci95", "model_win_rate", "mean_edge",
    }
    assert set(r["model"]) == {"log_loss", "brier", "accuracy"}
    assert set(r["market"]) == {"log_loss", "brier", "accuracy"}


def test_benchmark_binary_sharper_correct_model_beats_market():
    # Model confident on the realized side, market lukewarm; outcome = 1.
    r = benchmark_binary([0.9] * 10, [0.55] * 10, [1] * 10, n_bootstrap=200)
    assert r["diff_log_loss"] < 0
    assert r["model_win_rate"] == 1.0
    assert r["mean_edge"] == pytest.approx(0.9 - 0.55)
    assert r["diff_ci95"][1] < 0  # CI fully below 0


def test_benchmark_binary_overconfident_wrong_model_loses():
    # Model confident on outcome=1 but the realized outcome is 0.
    r = benchmark_binary([0.9] * 10, [0.55] * 10, [0] * 10, n_bootstrap=200)
    assert r["diff_log_loss"] > 0


def test_benchmark_binary_metrics_are_correct():
    import math

    r = benchmark_binary([0.75], [0.5], [1], n_bootstrap=50)
    assert r["model"]["log_loss"] == pytest.approx(-math.log(0.75))
    assert r["model"]["brier"] == pytest.approx((0.75 - 1) ** 2)
    assert r["model"]["accuracy"] == pytest.approx(1.0)  # round(0.75)==1
    assert r["market"]["accuracy"] == pytest.approx(0.0)  # round(0.5)==0 != 1


def test_benchmark_binary_edge_uses_realised_direction():
    # y==0 -> edge measured on the "not-event" side: (1-pm) - (1-pk) = pk - pm.
    r = benchmark_binary([0.3], [0.4], [0], n_bootstrap=50)
    assert r["mean_edge"] == pytest.approx(0.4 - 0.3)


def test_benchmark_binary_empty_input_raises():
    with pytest.raises(ValueError):
        benchmark_binary([], [], [])


# --- ou25_label ----------------------------------------------------------

def test_ou25_label_two_goals_is_under():
    assert ou25_label(1, 1) == 0
    assert ou25_label(2, 0) == 0


def test_ou25_label_three_goals_is_over():
    assert ou25_label(2, 1) == 1
    assert ou25_label(0, 3) == 1


def test_ou25_label_high_scoring_is_over():
    assert ou25_label(3, 2) == 1
