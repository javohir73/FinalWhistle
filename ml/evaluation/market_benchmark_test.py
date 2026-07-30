"""Tests for the closing-line benchmark (ml/evaluation/market_benchmark.py)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from ml.evaluation.market_benchmark import (
    DEVIG_METHODS,
    MatchedMatch,
    benchmark,
    benchmark_binary,
    devig,
    devig2,
    format_report,
    join_odds_to_rows,
    market_basis,
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


# --- devig methods (D0 §10) ----------------------------------------------

def test_default_stays_proportional_and_positional_calls_are_untouched():
    # The frozen q3 baseline (pipeline/run_calibrator_benchmark.py) calls this
    # positionally with three args. Every market number in
    # docs/MODEL-EXPERIMENTS.md was computed under proportional. Both would be
    # silently invalidated if the default ever moved.
    assert devig(1.60, 4.20, 6.00) == devig(1.60, 4.20, 6.00, method="proportional")
    raw = (1 / 1.60, 1 / 4.20, 1 / 6.00)
    total = sum(raw)
    assert devig(1.60, 4.20, 6.00) == pytest.approx(tuple(r / total for r in raw))


@pytest.mark.parametrize("method", DEVIG_METHODS)
def test_every_method_returns_a_normalized_ordered_triple(method):
    p = devig(1.60, 4.20, 6.00, method=method)
    assert sum(p) == pytest.approx(1.0)
    assert p[0] > p[1] > p[2]
    assert all(0.0 < x < 1.0 for x in p)


@pytest.mark.parametrize("method", DEVIG_METHODS)
def test_every_method_agrees_on_a_zero_vig_book(method):
    # With no margin there is nothing to remove, so the methods cannot
    # disagree. A method that does is solving the wrong equation.
    assert devig(2.0, 4.0, 4.0, method=method) == pytest.approx((0.5, 0.25, 0.25))


@pytest.mark.parametrize("method", DEVIG_METHODS)
def test_every_method_rejects_bad_odds(method):
    with pytest.raises(ValueError):
        devig(1.0, 3.0, 4.0, method=method)


def test_shin_and_power_shift_weight_toward_the_favourite():
    # Both model the favourite-longshot bias: proportional over-prices
    # longshots, so removing the margin proportionally leaves them too high.
    prop = devig(1.10, 12.0, 26.0, method="proportional")
    shin = devig(1.10, 12.0, 26.0, method="shin")
    power = devig(1.10, 12.0, 26.0, method="power")
    assert power[0] > shin[0] > prop[0]
    assert power[2] < shin[2] < prop[2]


def test_unknown_method_is_rejected_by_name():
    with pytest.raises(ValueError, match="unknown de-vig method"):
        devig(1.60, 4.20, 6.00, method="kelly")


@pytest.mark.parametrize("method", DEVIG_METHODS)
def test_blank_odds_are_rejected_not_propagated_as_nan(method):
    """A blank price scored as a PERFECT market prediction before this guard.

    `min(nan, nan, nan) <= 1.0` is False — every comparison against NaN is —
    so the row survived, devig returned (nan, nan, nan), and `_log_loss_one`
    clamped the NaN to `1 - eps`. The market got the best possible log loss on a
    match it never priced, while the same row contributed the worst possible
    Brier score.
    """
    nan = float("nan")
    with pytest.raises(ValueError, match="must be present"):
        devig(nan, 3.60, 4.50, method=method)
    with pytest.raises(ValueError, match="must be present"):
        devig(1.83, nan, nan, method=method)


def test_devig2_also_rejects_blank_odds():
    with pytest.raises(ValueError, match="must be present"):
        devig2(float("nan"), 2.0)


@pytest.mark.parametrize("method", DEVIG_METHODS)
def test_underround_books_are_handled_not_silently_degenerated(method):
    # Market-maximum families are a best-price envelope across books, so a
    # booksum below 1 is their normal state, not an anomaly. 71.5% of real MaxC
    # triples in the club captures are underround.
    odds = (2.2, 4.2, 4.4)
    assert sum(1 / o for o in odds) < 1.0
    p = devig(*odds, method=method)
    assert sum(p) == pytest.approx(1.0)
    assert all(0.0 < x < 1.0 for x in p)
    assert p[0] > p[1] > p[2]


def test_power_actually_solves_for_an_underround_book():
    # The bracket has to straddle k=1: an underround book needs k<1. A bracket
    # starting at 1.0 collapses onto its floor and returns the proportional
    # answer under a power label.
    odds = (2.2, 4.2, 4.4)
    assert devig(*odds, method="power") != pytest.approx(
        devig(*odds, method="proportional")
    )


def test_shin_falls_back_to_proportional_on_an_underround_book():
    # z is a share of insider money and cannot be negative, so Shin has no
    # solution here. The fallback is deliberate and documented, not a silent
    # bisection failure.
    odds = (2.2, 4.2, 4.4)
    assert devig(*odds, method="shin") == pytest.approx(
        devig(*odds, method="proportional")
    )


# --- provenance on benchmark output (D0 A3) -------------------------------

def _matched(basis, source="AvgC"):
    return MatchedMatch(
        date=date(2023, 8, 12), home="A", away="B",
        model_probs=(0.5, 0.3, 0.2), market_probs=(0.45, 0.3, 0.25), label="H",
        odds_basis=basis, odds_source=source,
    )


def test_market_basis_reports_a_single_basis():
    b = market_basis([_matched("closing"), _matched("closing")])
    assert b["odds_basis"] == "closing"
    assert b["mixed_basis"] is False
    assert b["odds_sources"] == ["AvgC"]


def test_market_basis_flags_a_mixed_set_instead_of_picking_a_label():
    b = market_basis([_matched("closing", "AvgC"), _matched("pre_closing", "Avg")])
    assert b["odds_basis"] == "mixed"
    assert b["mixed_basis"] is True
    assert b["odds_basis_values"] == ["closing", "pre_closing"]


def test_unlabelled_odds_report_as_unknown_not_as_closing():
    # The API-Football path attaches no basis. Absence must read as absence.
    b = market_basis([_matched(None, None)])
    assert b["odds_basis"] == "unknown"
    assert b["odds_sources"] == ["unknown"]


def test_report_header_names_the_basis_it_actually_scored():
    result = benchmark([_matched("closing")] * 4)
    assert "Closing-line benchmark" in format_report(
        result, "T", {"odds_basis": "closing"}
    )
    assert "PRE-CLOSING" in format_report(result, "T", {"odds_basis": "pre_closing"})
    assert "MIXED" in format_report(result, "T", {"odds_basis": "mixed"})
    # No provenance means nothing has been established — not "closing".
    assert "UNKNOWN" in format_report(result, "T")


def test_result_to_json_carries_provenance_and_stays_additive_without_it():
    result = benchmark([_matched("closing")] * 4)
    plain = result_to_json(result, "d", "t")
    assert "provenance" not in plain  # existing consumers see the old shape
    withp = result_to_json(result, "d", "t", {"odds_basis": "closing", "x": 1})
    assert withp["provenance"]["odds_basis"] == "closing"
    assert {k: v for k, v in withp.items() if k != "provenance"} == plain


@pytest.mark.parametrize("method", DEVIG_METHODS)
def test_methods_are_deterministic(method):
    # The solvers are bisections with a fixed iteration budget; a benchmark
    # that moved between runs would be unreproducible.
    assert devig(1.83, 3.60, 4.50, method=method) == devig(
        1.83, 3.60, 4.50, method=method
    )


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
