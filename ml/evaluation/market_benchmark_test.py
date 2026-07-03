"""Tests for the closing-line benchmark (ml/evaluation/market_benchmark.py)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from ml.evaluation.market_benchmark import (
    MatchedMatch,
    benchmark,
    devig,
    format_report,
    join_odds_to_rows,
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
