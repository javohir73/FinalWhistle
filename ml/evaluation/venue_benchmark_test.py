"""Adversarial tests for the shadow venue benchmark. Synthetic data proves
CODE PATHS only -- nothing here is real-world validation, and the docs say so."""

from datetime import datetime, timedelta, timezone

import pytest

from ml.evaluation.venue_benchmark import (
    NOT_READY,
    READY,
    BenchmarkInputError,
    MatchObservation,
    chronological_split,
    evaluate_holdout,
    run_benchmark,
)

KICKOFF = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)


def _observation(match_id=1, *, venue="kalshi", outcome="home",
                 kickoff=KICKOFF, captured=None, model=(0.5, 0.3, 0.2),
                 raw=(0.52, 0.30, 0.24), competition="Premier League 2026-27",
                 leg_captured_at=None):
    return MatchObservation(
        match_id=match_id, venue=venue, competition=competition,
        kickoff_utc=kickoff, captured_at=captured or (kickoff - timedelta(hours=1)),
        outcome=outcome, model_probs=model, venue_probs_raw=raw,
        leg_captured_at=leg_captured_at)


def _many(n, *, venue="kalshi", start=KICKOFF, spread_days=1, **kwargs):
    return [
        _observation(match_id=i + 1, venue=venue,
                     kickoff=start + timedelta(days=i * spread_days), **kwargs)
        for i in range(n)
    ]


# --- fail closed at construction --------------------------------------------


def test_vig_normalization_is_explicit_and_raw_prices_are_retained():
    observation = _observation(raw=(0.55, 0.30, 0.25))

    assert observation.venue_probs_raw == (0.55, 0.30, 0.25)
    assert observation.book_sum == pytest.approx(1.10)
    assert sum(observation.venue_probs) == pytest.approx(1.0)
    assert observation.venue_probs[0] == pytest.approx(0.5)


@pytest.mark.parametrize("kwargs,fragment", [
    ({"model": (0.5, float("nan"), 0.2)}, "out-of-domain"),
    ({"model": (0.5, float("inf"), 0.2)}, "out-of-domain"),
    ({"model": (1.2, -0.1, -0.1)}, "out-of-domain"),
    ({"model": (0.2, 0.2, 0.2)}, "sum to"),
    ({"raw": (0.2, 0.2, 0.2)}, "book sum"),
    ({"raw": (0.9, 0.5, 0.4)}, "book sum"),
    ({"raw": (0.5, 0.3, float("nan"))}, "out-of-domain"),
    ({"outcome": "win"}, "unknown outcome"),
    ({"outcome": ""}, "unknown outcome"),
    ({"venue": "  "}, "non-empty"),
])
def test_malformed_observations_are_refused_at_construction(kwargs, fragment):
    with pytest.raises(BenchmarkInputError, match=fragment):
        _observation(**kwargs)


def test_naive_and_misordered_timestamps_are_refused():
    with pytest.raises(BenchmarkInputError, match="timezone-aware"):
        _observation(kickoff=KICKOFF.replace(tzinfo=None))
    with pytest.raises(BenchmarkInputError, match="timezone-aware"):
        _observation(captured=KICKOFF.replace(tzinfo=None) - timedelta(hours=1))
    with pytest.raises(BenchmarkInputError, match="after kickoff"):
        _observation(captured=KICKOFF + timedelta(seconds=1))


def test_a_quote_exactly_at_kickoff_is_still_pre_match():
    assert _observation(captured=KICKOFF).captured_at == KICKOFF


# --- the split moves whole matches, chronologically --------------------------


def test_all_observations_for_a_match_stay_together():
    """The leakage rule: splitting rows would let a match's kalshi row train
    what its polymarket row is judged on."""
    observations = []
    for i in range(10):
        kickoff = KICKOFF + timedelta(days=i)
        observations.append(_observation(match_id=i + 1, kickoff=kickoff))
        observations.append(_observation(match_id=i + 1, venue="polymarket",
                                         kickoff=kickoff))

    train, holdout, diagnostics = chronological_split(
        observations, holdout_fraction=0.3)

    train_ids = {o.match_id for o in train}
    holdout_ids = {o.match_id for o in holdout}
    assert not train_ids & holdout_ids, "a match appears on both sides"
    assert diagnostics["holdout_matches"] == 3
    assert max(o.kickoff_utc for o in train) < min(o.kickoff_utc for o in holdout)


def test_the_split_is_chronological_regardless_of_input_order():
    observations = _many(10)
    shuffled = list(reversed(observations))

    _, holdout_a, _ = chronological_split(observations, holdout_fraction=0.2)
    _, holdout_b, _ = chronological_split(shuffled, holdout_fraction=0.2)

    assert {o.match_id for o in holdout_a} == {9, 10}
    assert {o.match_id for o in holdout_a} == {o.match_id for o in holdout_b}


def test_conflicting_kickoffs_for_one_match_fail_closed():
    observations = [
        _observation(match_id=1, kickoff=KICKOFF),
        _observation(match_id=1, venue="polymarket",
                     kickoff=KICKOFF + timedelta(days=2)),
    ]

    with pytest.raises(BenchmarkInputError, match="two different"):
        chronological_split(observations)


def test_competition_diagnostics_flag_holdout_only_competitions():
    observations = _many(8, competition="Premier League 2026-27")
    observations += [
        _observation(match_id=100, competition="FA Cup 2026-27",
                     kickoff=KICKOFF + timedelta(days=40)),
    ]

    _, _, diagnostics = chronological_split(observations, holdout_fraction=0.3)

    cup = diagnostics["competitions"]["FA Cup 2026-27"]
    assert cup["holdout_only"] is True
    assert cup["train_matches"] == 0


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.2, 1.5])
def test_degenerate_holdout_fractions_are_refused(fraction):
    with pytest.raises(BenchmarkInputError, match="holdout_fraction"):
        chronological_split(_many(4), holdout_fraction=fraction)


# --- NOT READY never ranks ---------------------------------------------------


def test_below_minimum_n_is_not_ready_with_no_verdict_and_no_metrics():
    result = evaluate_holdout(_many(5), min_matches=50)

    group = result["groups"][0]
    assert group["status"] == NOT_READY
    assert group["n_matches"] == 5
    assert "verdict" not in group
    assert "model" not in group
    assert "delta_log_loss_model_minus_venue" not in group
    assert "no verdict" in group["reason"]


def test_zero_observations_produce_an_empty_deterministic_report():
    result = evaluate_holdout([], min_matches=50)

    assert result["groups"] == []


def test_one_venue_ready_does_not_rank_the_other_tiny_one():
    observations = _many(60, venue="kalshi")
    observations += _many(3, venue="polymarket", start=KICKOFF + timedelta(hours=1))

    result = evaluate_holdout(observations, min_matches=50, n_bootstrap=200)

    by_venue = {g["venue"]: g for g in result["groups"]}
    assert by_venue["kalshi"]["status"] == READY
    assert by_venue["polymarket"]["status"] == NOT_READY


def test_duplicate_observations_for_one_match_and_venue_fail_closed():
    observations = [_observation(match_id=1), _observation(match_id=1)]

    with pytest.raises(BenchmarkInputError, match="more observations than"):
        evaluate_holdout(observations, min_matches=1)


# --- metrics, uncertainty, determinism ---------------------------------------


def test_ready_group_reports_all_three_contestants_on_identical_matches():
    result = evaluate_holdout(_many(60), min_matches=50, n_bootstrap=200)

    group = result["groups"][0]
    assert group["status"] == READY
    assert group["model"]["n"] == 60
    assert group["venue_normalized"]["n"] == 60
    assert group["baseline_uniform"]["n"] == 60
    assert group["baseline_uniform"]["log_loss"] == pytest.approx(1.0986, abs=1e-3)
    assert group["model"]["reliability"]["bins"], "reliability table present"
    assert group["bootstrap"]["unit"] == "match"
    assert group["delta_ci95_match_clustered"] is not None
    assert group["verdict"] in {"model_beats_venue", "venue_beats_model",
                                "inconclusive"}


def test_the_report_is_deterministic_for_a_fixed_seed():
    observations = _many(60)

    first = evaluate_holdout(observations, min_matches=50, n_bootstrap=300,
                             seed=7)
    second = evaluate_holdout(list(reversed(observations)), min_matches=50,
                              n_bootstrap=300, seed=7)

    assert first == second


def test_a_clearly_better_model_earns_its_verdict():
    """Model puts 0.9 on the true outcome, the venue is near-uniform: the
    clustered CI must exclude zero on the negative side."""
    observations = [
        _observation(match_id=i + 1, kickoff=KICKOFF + timedelta(days=i),
                     model=(0.9, 0.06, 0.04), raw=(0.36, 0.34, 0.32))
        for i in range(60)
    ]

    result = evaluate_holdout(observations, min_matches=50, n_bootstrap=300)

    group = result["groups"][0]
    assert group["verdict"] == "model_beats_venue"
    assert group["delta_ci95_match_clustered"][1] < 0


def test_run_benchmark_evaluates_the_holdout_only():
    """Train matches must not appear in the scored set."""
    observations = _many(100)

    result = run_benchmark(observations, holdout_fraction=0.3,
                           min_matches=10, n_bootstrap=200)

    assert result["split"]["holdout_matches"] == 30
    assert result["groups"][0]["n_matches"] == 30
    assert "future calibration" in result["note"]


# --- review round 2: kickoff cohorts and gate validation ---------------------


def test_a_simultaneous_kickoff_cohort_never_splits_across_the_boundary():
    """A Saturday 15:00 round is one cohort. Cutting the sorted list by count
    landed the boundary inside it, breaking strict train-before-holdout for
    anything ever fitted on the train side."""
    observations = [
        _observation(match_id=i + 1, kickoff=KICKOFF + timedelta(days=i))
        for i in range(7)
    ]
    cohort_kickoff = KICKOFF + timedelta(days=7)
    observations += [
        _observation(match_id=100 + i, kickoff=cohort_kickoff) for i in range(3)
    ]

    train, holdout, diagnostics = chronological_split(
        observations, holdout_fraction=0.2)  # requests 2 of 10

    holdout_ids = {o.match_id for o in holdout}
    assert holdout_ids == {100, 101, 102}, "the whole cohort moved together"
    assert diagnostics["holdout_matches"] == 3
    assert diagnostics["requested_holdout_matches"] == 2
    assert max(o.kickoff_utc for o in train) < min(o.kickoff_utc for o in holdout)


def test_an_all_simultaneous_dataset_has_no_valid_boundary_and_fails_closed():
    observations = [
        _observation(match_id=i + 1, kickoff=KICKOFF) for i in range(6)
    ]

    with pytest.raises(BenchmarkInputError, match="no valid chronological"):
        chronological_split(observations, holdout_fraction=0.5)


def test_leg_timestamps_and_skew_travel_with_the_observation():
    legs = (KICKOFF - timedelta(minutes=10), KICKOFF - timedelta(minutes=5),
            KICKOFF - timedelta(minutes=2))
    observation = _observation(leg_captured_at=legs)

    assert observation.leg_captured_at == legs
    assert observation.cross_leg_skew_seconds == 480.0

    with pytest.raises(BenchmarkInputError, match="pre-match"):
        _observation(leg_captured_at=(
            KICKOFF - timedelta(minutes=5), KICKOFF - timedelta(minutes=2),
            KICKOFF + timedelta(seconds=1)))
    with pytest.raises(BenchmarkInputError, match="timezone-aware"):
        _observation(leg_captured_at=(
            KICKOFF.replace(tzinfo=None), KICKOFF, KICKOFF))


def test_degenerate_evaluation_gates_fail_closed():
    with pytest.raises(BenchmarkInputError, match="min_matches"):
        evaluate_holdout(_many(5), min_matches=0)
    with pytest.raises(BenchmarkInputError, match="n_bootstrap"):
        evaluate_holdout(_many(60), min_matches=50, n_bootstrap=0)
