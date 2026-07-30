"""Tests for the D0-B totals benchmark (offline, hermetic).

The failure modes worth testing here are not "does it compute a log loss" —
they are the ones that produce a plausible number that is wrong: an inverted
market column, a constant fitted on the data it is scored on, a pooled
pre-closing row reported as closing, and a model column that has seen the
result.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from ml.evaluation.club_totals_benchmark import (
    MatchedTotal,
    binary_log_loss,
    build_matched_totals,
    clustered_deltas,
    constant_rate,
    information_share,
    information_share_ci,
    market_p_over,
    ou_label,
    score_totals,
    totals_market_basis,
)
from ml.evaluation.club_walkforward import ClubMatch, EloConfig, GridConfig, replay

COMP = "Premier League"


def _mt(season="2324", d=date(2024, 1, 6), model=0.55, control=0.55, market=0.55,
        label=1, basis="closing", source="AvgC") -> MatchedTotal:
    return MatchedTotal(
        date=d, season=season, home="A", away="B", model_p_over=model,
        control_p_over=control, market_p_over=market, label=label,
        odds_basis=basis, odds_source=source, line=2.5,
    )


# --- market orientation ---------------------------------------------------

def test_market_p_over_is_oriented_by_the_over_price_not_the_under():
    # A short OVER price must mean a HIGH P(over). Swapping devig2's positional
    # arguments returns P(under), which is also a plausible-looking probability
    # near 0.5 -- nothing downstream would look wrong.
    p = market_p_over(1.50, 2.60)
    assert p > 0.5
    assert p == pytest.approx((1 / 1.50) / (1 / 1.50 + 1 / 2.60))


def test_market_p_over_is_a_half_on_a_fair_coin():
    assert market_p_over(2.0, 2.0) == pytest.approx(0.5)


def test_market_p_over_rejects_an_unusable_price():
    with pytest.raises(ValueError):
        market_p_over(float("nan"), 1.95)
    with pytest.raises(ValueError):
        market_p_over(0.42, 2.83)  # the real D1_1920 corrupt row


# --- labels ---------------------------------------------------------------

def test_ou_label_boundary_is_strictly_above_the_line():
    assert ou_label(1, 1) == 0  # 2 goals
    assert ou_label(2, 0) == 0
    assert ou_label(2, 1) == 1  # 3 goals
    assert ou_label(0, 3) == 1


def test_ou_label_honours_a_non_25_line():
    # A 3.5 book must not be scored against a 2.5 label.
    assert ou_label(2, 1, line=3.5) == 0
    assert ou_label(2, 2, line=3.5) == 1


# --- the join -------------------------------------------------------------

def _fixture_matches() -> list[ClubMatch]:
    out = []
    for i, (h, a, gh, ga) in enumerate([
        ("Arsenal", "Chelsea", 2, 1), ("Chelsea", "Spurs", 0, 0),
        ("Spurs", "Arsenal", 3, 2), ("Arsenal", "Spurs", 1, 1),
        ("Chelsea", "Arsenal", 2, 2), ("Spurs", "Chelsea", 4, 0),
    ]):
        out.append(ClubMatch(season="2324", home=h, away=a, goals_home=gh,
                             goals_away=ga, date=f"2024-01-{i + 1:02d}"))
    return out


def _priced(matches, over=1.90, under=1.95, basis="closing", source="AvgC"):
    return [{
        "date": date.fromisoformat(m.date), "home_team": m.home,
        "away_team": m.away, "home_score": m.goals_home,
        "away_score": m.goals_away, "odds_over": over, "odds_under": under,
        "line": 2.5, "odds_source": source, "odds_basis": basis,
        "odds_bookmaker": "market average",
    } for m in matches]


def test_join_matches_on_date_and_both_team_names():
    ms = _fixture_matches()
    elo, grid = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    matched, unpriced = build_matched_totals(ms, pre, elo, grid, grid, _priced(ms))
    assert len(matched) == len(ms)
    assert unpriced == []


def test_a_priced_row_with_no_replayed_match_is_returned_not_dropped():
    # Silently dropping it would shrink the denominator invisibly.
    ms = _fixture_matches()
    elo, grid = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    rows = _priced(ms)
    rows.append({**rows[0], "home_team": "Nobody FC"})
    matched, unpriced = build_matched_totals(ms, pre, elo, grid, grid, rows)
    assert len(matched) == len(ms)
    assert [r["home_team"] for r in unpriced] == ["Nobody FC"]


def test_seasons_without_a_price_still_drive_the_replay():
    """Burn-in seasons must move the ratings even though they are never scored.

    Restricting the replay to priced seasons would hand every club a cold-start
    rating in the first priced season, changing every probability downstream.
    """
    ms = _fixture_matches()
    burn = [ClubMatch(season="1819", home="Arsenal", away="Chelsea",
                      goals_home=5, goals_away=0, date="2019-01-01")]
    elo, grid = EloConfig(), GridConfig()

    without = build_matched_totals(ms, replay(ms, elo, COMP), elo, grid, grid,
                                   _priced(ms))[0]
    full = burn + ms
    with_burn = build_matched_totals(full, replay(full, elo, COMP), elo, grid,
                                     grid, _priced(ms))[0]
    assert len(without) == len(with_burn) == len(ms)
    assert without[0].model_p_over != with_burn[0].model_p_over


def test_control_column_differs_from_served_when_base_differs():
    ms = _fixture_matches()
    elo = EloConfig()
    pre = replay(ms, elo, COMP)
    matched, _ = build_matched_totals(
        ms, pre, elo, GridConfig(base=1.44), GridConfig(base=1.20), _priced(ms),
    )
    # A higher base means more goals means a higher P(over), every match.
    assert all(m.model_p_over > m.control_p_over for m in matched)


def test_mismatched_lengths_raise_rather_than_zip_short():
    ms = _fixture_matches()
    elo, grid = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    with pytest.raises(ValueError, match="length mismatch"):
        build_matched_totals(ms, pre[:-1], elo, grid, grid, _priced(ms))


# --- basis labelling ------------------------------------------------------

def test_basis_label_reports_a_clean_run_plainly():
    assert totals_market_basis([_mt(), _mt()]) == "closing (AvgC)"


def test_basis_label_shouts_when_a_run_pooled_two_markets():
    mixed = [_mt(), _mt(basis="pre_closing", source="Avg")]
    label = totals_market_basis(mixed)
    assert label.startswith("MIXED(")
    assert "pre_closing" in label and "closing" in label


def test_basis_label_of_an_empty_run_is_unknown_not_closing():
    assert totals_market_basis([]) == "unknown"


# --- the constant baseline ------------------------------------------------

def test_constant_rate_uses_only_the_fit_seasons():
    rows = [_mt(season="2122", label=1), _mt(season="2122", label=1),
            _mt(season="2324", label=0), _mt(season="2324", label=0)]
    assert constant_rate(rows, ["2122"]) == 1.0
    assert constant_rate(rows, ["2324"]) == 0.0


def test_constant_rate_raises_when_no_row_is_in_the_fit_seasons():
    with pytest.raises(ValueError, match="no matched rows in fit seasons"):
        constant_rate([_mt(season="2324")], ["1920"])


def test_score_totals_refuses_to_fit_the_constant_in_sample():
    """The single most flattering mistake available, so it is a hard error."""
    rows = [_mt(season="2324", label=1), _mt(season="2324", label=0)]
    with pytest.raises(ValueError, match="in-sample"):
        score_totals(rows, ["2324"], ["2324"])


def test_score_totals_raises_when_the_scored_window_is_empty():
    with pytest.raises(ValueError, match="no matched rows in scored seasons"):
        score_totals([_mt(season="2122")], ["2122"], ["2425"])


# --- scoring --------------------------------------------------------------

def _split_rows(n=40):
    """Half fit, half scored; overs alternate so the rate is a clean 0.5."""
    rows = []
    for i in range(n):
        rows.append(_mt(season="2122" if i < n // 2 else "2324",
                        d=date(2022, 1, 1) if i < n // 2 else date(2024, 1, 1),
                        label=i % 2))
    return rows


def test_a_perfect_model_beats_the_market_and_the_sign_is_negative():
    rows = [_mt(season="2122", label=i % 2) for i in range(10)] + [
        _mt(season="2324", d=date(2024, 1, 1), label=i % 2,
            model=0.999 if i % 2 else 0.001, control=0.5, market=0.55)
        for i in range(10)
    ]
    r = score_totals(rows, ["2122"], ["2324"])
    assert r["model_minus_market"] < 0  # negative = model closer to reality


def test_an_overconfident_wrong_model_loses_and_the_sign_is_positive():
    rows = [_mt(season="2122", label=i % 2) for i in range(10)] + [
        _mt(season="2324", d=date(2024, 1, 1), label=i % 2,
            model=0.001 if i % 2 else 0.999, control=0.5, market=0.55)
        for i in range(10)
    ]
    assert score_totals(rows, ["2122"], ["2324"])["model_minus_market"] > 0


def test_identical_columns_produce_exactly_zero_difference():
    r = score_totals(_split_rows(), ["2122"], ["2324"])
    assert r["model_minus_market"] == 0.0
    assert r["model_minus_control"] == 0.0


def test_metrics_are_computed_not_guessed():
    rows = [_mt(season="2122", label=1)] + [
        _mt(season="2324", d=date(2024, 1, 1), label=1, model=0.75,
            control=0.75, market=0.75)
    ]
    r = score_totals(rows, ["2122"], ["2324"])
    assert r["model"]["log_loss"] == pytest.approx(-math.log(0.75))
    assert r["model"]["brier"] == pytest.approx(0.25**2)
    assert r["model"]["accuracy"] == 1.0


def test_accuracy_does_not_resolve_an_exact_coin_flip_by_bankers_rounding():
    # round(0.5) == 0 in Python. A predictor that says exactly 0.5 has not
    # predicted "under"; it has declined to predict.
    rows = [_mt(season="2122", label=1)] + [
        _mt(season="2324", d=date(2024, 1, 1), label=1, model=0.5)
    ]
    assert score_totals(rows, ["2122"], ["2324"])["model"]["accuracy"] == 0.0
    rows[1] = _mt(season="2324", d=date(2024, 1, 1), label=0, model=0.5)
    assert score_totals(rows, ["2122"], ["2324"])["model"]["accuracy"] == 1.0


# --- clustering -----------------------------------------------------------

def test_iso_week_is_the_calendar_week_of_the_match():
    assert _mt(d=date(2024, 1, 6)).iso_week == "2024-W01"
    assert _mt(d=date(2024, 12, 30)).iso_week == "2025-W01"  # ISO year rolls


def test_clustered_deltas_buckets_by_the_requested_key():
    rows = [_mt(season="2324", d=date(2024, 1, 6)),
            _mt(season="2324", d=date(2024, 1, 7)),   # same ISO week
            _mt(season="2425", d=date(2024, 9, 1))]
    by_week = clustered_deltas(rows, [1.0, 2.0, 3.0], "iso_week")
    assert by_week["2024-W01"] == [1.0, 2.0]
    by_season = clustered_deltas(rows, [1.0, 2.0, 3.0], "season")
    assert by_season["2324"] == [1.0, 2.0] and by_season["2425"] == [3.0]


def test_clustered_deltas_rejects_an_unknown_key_and_a_length_mismatch():
    with pytest.raises(ValueError, match="unknown cluster key"):
        clustered_deltas([_mt()], [1.0], "matchday")
    with pytest.raises(ValueError, match="length mismatch"):
        clustered_deltas([_mt()], [1.0, 2.0], "season")


# --- information share ----------------------------------------------------

def test_information_share_is_one_when_the_model_matches_the_market():
    r = {"model_minus_market": 0.0, "market_minus_constant": -0.05}
    assert information_share(r) == pytest.approx(1.0)


def test_information_share_is_zero_when_the_model_only_matches_the_constant():
    r = {"model_minus_market": 0.05, "market_minus_constant": -0.05}
    assert information_share(r) == pytest.approx(0.0)


def test_information_share_is_none_when_there_is_no_budget_to_share():
    # If the market does not beat the constant there is no information budget,
    # and a percentage of it would be a number with no referent.
    assert information_share(
        {"model_minus_market": 0.01, "market_minus_constant": +0.02}
    ) is None
    assert information_share(
        {"model_minus_market": 0.01, "market_minus_constant": 0.0}
    ) is None


def test_binary_log_loss_clips_rather_than_returning_infinity():
    assert binary_log_loss(0.0, 1) < float("inf")
    assert binary_log_loss(1.0, 0) < float("inf")


# --- fixes from the adversarial review -----------------------------------

def test_the_model_is_priced_at_the_line_the_market_and_label_use():
    """A 3.5 book must not be scored with a 2.5 model probability.

    The first cut took ``line`` from the signature for the model column while
    the label and the market came from ``rec["line"]`` — harmless while every
    family is 2.5, and a silent mispricing the moment one is not.
    """
    ms = _fixture_matches()
    elo, grid = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    at_25 = build_matched_totals(ms, pre, elo, grid, grid, _priced(ms))[0]
    rows35 = [{**r, "line": 3.5} for r in _priced(ms)]
    at_35 = build_matched_totals(ms, pre, elo, grid, grid, rows35)[0]
    # A higher line means fewer matches go over, so P(over) must fall.
    assert all(b.model_p_over < a.model_p_over for a, b in zip(at_25, at_35))
    assert all(r.line == 3.5 for r in at_35)


def test_mixed_lines_in_one_run_are_refused():
    ms = _fixture_matches()
    elo, grid = EloConfig(), GridConfig()
    pre = replay(ms, elo, COMP)
    rows = _priced(ms)
    rows[0] = {**rows[0], "line": 3.5}
    with pytest.raises(ValueError, match="mix over/under lines"):
        build_matched_totals(ms, pre, elo, grid, grid, rows)


def test_a_duplicate_match_key_raises_instead_of_reporting_zero_unjoined():
    """A dict index silently overwrites. That would drop a match AND still
    report unjoined == 0 — a coverage claim true only because the evidence
    against it was overwritten."""
    ms = _fixture_matches()
    dup = ms + [ms[0]]
    elo, grid = EloConfig(), GridConfig()
    pre = replay(dup, elo, COMP)
    with pytest.raises(ValueError, match="duplicate match key"):
        build_matched_totals(dup, pre, elo, grid, grid, _priced(ms))


def test_score_totals_reports_model_minus_constant_with_its_own_deltas():
    """The comparison `pipeline/leagues.py` cites to justify both shipped
    overrides. The first cut computed it as a difference of two LEVELS and so
    reported it with no uncertainty at all."""
    rows = [_mt(season="2122", label=i % 2) for i in range(10)] + [
        _mt(season="2324", d=date(2024, 1, 1), label=i % 2, model=0.9 if i % 2 else 0.1)
        for i in range(10)
    ]
    r = score_totals(rows, ["2122"], ["2324"])
    assert "model_minus_constant" in r
    d = r["deltas_model_minus_constant"]
    assert len(d) == r["n_matches"]
    assert r["model_minus_constant"] == pytest.approx(sum(d) / len(d))
    # A sharp correct model must beat the constant.
    assert r["model_minus_constant"] < 0


def test_information_share_ci_widens_with_a_noisy_budget():
    rows = [_mt(season="2324", d=date(2024, 1, 1) + timedelta(days=i), label=i % 2)
            for i in range(40)]
    gap = [0.02] * 40
    budget = [-0.03] * 40
    tight = information_share_ci(rows, gap, budget, n_bootstrap=200)
    # A constant delta series has no resampling noise at all.
    assert tight["ci95"][0] == pytest.approx(tight["ci95"][1])
    noisy = information_share_ci(
        rows, gap, [-0.03 if i % 2 else -0.001 for i in range(40)], n_bootstrap=200,
    )
    assert noisy["ci95"][1] - noisy["ci95"][0] > 0.0


def test_information_share_ci_counts_resamples_with_no_budget():
    """A budget that can vanish under resampling is the honest reason a share
    cannot be quoted to a tenth of a percent."""
    rows = [_mt(season="2324", d=date(2024, 1, 1) + timedelta(days=i), label=i % 2)
            for i in range(20)]
    out = information_share_ci(
        rows, [0.01] * 20, [+0.05] * 20, n_bootstrap=100,
    )
    assert out["ci95"] is None
    assert out["n_undefined"] == 100


def test_information_share_ci_rejects_a_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        information_share_ci([_mt()], [1.0, 2.0], [1.0])
