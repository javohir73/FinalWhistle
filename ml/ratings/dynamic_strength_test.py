"""Focused behavioral tests for the dynamic strength/tempo model."""
from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ml.models.vnext import MatchContext
from ml.ratings.dynamic_strength import (
    DynamicModelConfig,
    DynamicStrengthTempoModel,
    GroupPrior,
)


T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def _play(
    model: DynamicStrengthTempoModel,
    match_id: str,
    home: str,
    away: str,
    home_goals: int,
    away_goals: int,
    at: datetime,
):
    prediction = model.predict(match_id, home, away, at)
    model.update(match_id, home_goals, away_goals, at + timedelta(hours=2))
    return prediction


def test_result_cannot_leak_into_its_own_prediction():
    untouched = DynamicStrengthTempoModel()
    model = DynamicStrengthTempoModel()

    before_result = model.predict("m1", "A", "B", T0)
    control = untouched.predict("control", "A", "B", T0)
    assert before_result.strength_log_ratio == control.strength_log_ratio
    assert before_result.log_total_goals == control.log_total_goals
    assert before_result.evidence_count == 0

    with pytest.raises(ValueError, match="before predicting"):
        DynamicStrengthTempoModel().update("unknown", 2, 0, T0)

    model.update("m1", 2, 0, T0 + timedelta(hours=2))
    after_result = model.predict("m2", "A", "C", T0 + timedelta(days=1))
    assert after_result.strength_log_ratio > before_result.strength_log_ratio
    assert after_result.evidence_count == 1


def test_strength_update_moves_winner_up_and_loser_down():
    model = DynamicStrengthTempoModel()
    prediction = _play(model, "m1", "A", "B", 3, 0, T0)
    home = model.team_state("A", T0 + timedelta(hours=2))
    away = model.team_state("B", T0 + timedelta(hours=2))

    assert prediction.lambda_home == pytest.approx(prediction.lambda_away)
    assert home.strength > 0.0
    assert away.strength < 0.0
    assert home.strength == pytest.approx(-away.strength)


def test_strength_and_tempo_axes_are_isolated():
    model = DynamicStrengthTempoModel()
    baseline = model.predict("high-draw", "A", "B", T0)
    model.update("high-draw", 4, 4, T0 + timedelta(hours=2))

    home = model.team_state("A", T0 + timedelta(hours=2))
    away = model.team_state("B", T0 + timedelta(hours=2))
    assert home.strength == pytest.approx(0.0)
    assert away.strength == pytest.approx(0.0)
    assert home.tempo > 0.0
    assert away.tempo > 0.0

    next_prediction = model.predict("next", "A", "B", T0 + timedelta(days=1))
    assert next_prediction.strength_log_ratio == pytest.approx(0.0)
    assert next_prediction.total_expected_goals > baseline.total_expected_goals
    assert next_prediction.lambda_home / next_prediction.lambda_away == pytest.approx(1.0)


def test_cold_start_uses_parent_group_prior():
    model = DynamicStrengthTempoModel(
        group_priors={
            "elite": GroupPrior(
                strength_mean=0.6,
                tempo_mean=0.2,
                strength_variance=0.2,
                tempo_variance=0.1,
            ),
            "developing": GroupPrior(
                strength_mean=-0.4,
                tempo_mean=-0.1,
                strength_variance=0.8,
                tempo_variance=0.3,
            ),
        },
        team_groups={"A": "elite", "B": "developing"},
    )
    prediction = model.predict("m1", "A", "B", T0)

    assert prediction.strength_log_ratio == pytest.approx(1.0)
    assert prediction.log_total_goals == pytest.approx(math.log(2.6) + 0.05)
    assert prediction.strength_std == pytest.approx(math.sqrt(1.0))


def test_stale_state_decays_toward_parent_prior():
    config = DynamicModelConfig(decay_half_life_days=10.0)
    model = DynamicStrengthTempoModel(config)
    _play(model, "m1", "A", "B", 3, 0, T0)
    fresh = model.team_state("A", T0 + timedelta(hours=2))
    stale = model.team_state("A", T0 + timedelta(days=10, hours=2))

    assert stale.strength == pytest.approx(fresh.strength / 2.0)
    assert stale.tempo == pytest.approx(fresh.tempo / 2.0)
    assert abs(stale.strength) < abs(fresh.strength)


def test_uncertainty_shrinks_with_evidence_and_grows_with_staleness():
    config = DynamicModelConfig(decay_half_life_days=5.0)
    model = DynamicStrengthTempoModel(config)
    cold = model.predict("m1", "A", "B", T0)
    model.update("m1", 1, 0, T0 + timedelta(hours=2))

    learned = model.team_state("A", T0 + timedelta(hours=2))
    stale = model.team_state("A", T0 + timedelta(days=100))
    assert learned.strength_variance < 1.0
    assert learned.tempo_variance < 0.25
    assert stale.strength_variance > learned.strength_variance
    assert stale.tempo_variance > learned.tempo_variance
    assert stale.strength_variance == pytest.approx(1.0, rel=1e-5)
    assert stale.tempo_variance == pytest.approx(0.25, rel=1e-5)
    assert cold.strength_std == pytest.approx(math.sqrt(2.0))


def test_snapshot_round_trip_is_json_serializable_and_keeps_pending_ticket():
    model = DynamicStrengthTempoModel(
        group_priors={"elite": GroupPrior(strength_mean=0.3)},
        team_groups={"A": "elite"},
    )
    model.predict("pending", "A", "B", T0)
    payload = json.loads(json.dumps(model.snapshot()))
    restored = DynamicStrengthTempoModel.restore(payload)

    assert restored.snapshot() == payload
    restored.update("pending", 2, 1, T0 + timedelta(hours=2))
    assert restored.completed_match_ids == ("pending",)
    assert restored.team_state("A", T0 + timedelta(hours=2)).evidence_count == 1


def test_multiple_future_fixtures_for_same_team_can_be_predicted():
    model = DynamicStrengthTempoModel()
    first = model.predict("m1", "A", "B", T0)
    second = model.predict("m2", "A", "C", T0)

    assert model.pending_match_ids == ("m1", "m2")
    assert first.strength_log_ratio == second.strength_log_ratio


def test_repeated_forecast_is_non_registering_and_does_not_mutate_state():
    model = DynamicStrengthTempoModel()
    before = model.snapshot()

    first = model.forecast("daily-refresh", "A", "B", T0)
    second = model.forecast("daily-refresh", "A", "B", T0)

    assert first == second
    assert model.snapshot() == before
    assert model.pending_match_ids == ()


def test_overlapping_predictions_accumulate_learning_in_result_order():
    model = DynamicStrengthTempoModel()
    model.predict("m1", "A", "B", T0)
    model.predict("m2", "A", "C", T0)

    model.update("m1", 2, 0, T0 + timedelta(days=1))
    after_first = model.team_state("A", T0 + timedelta(days=1))
    model.update("m2", 2, 0, T0 + timedelta(days=2))
    after_second = model.team_state("A", T0 + timedelta(days=2))

    assert after_first.evidence_count == 1
    assert after_second.evidence_count == 2
    assert after_second.strength > after_first.strength


def test_overlapping_predictions_reject_out_of_order_results_without_mutation():
    model = DynamicStrengthTempoModel()
    model.predict("earlier", "A", "B", T0)
    model.predict("later", "A", "C", T0)
    model.update("later", 1, 0, T0 + timedelta(days=2))
    state_after_later = model.team_state("A", T0 + timedelta(days=2))

    with pytest.raises(ValueError, match="precedes the latest available state"):
        model.update("earlier", 1, 0, T0 + timedelta(days=1))

    assert model.team_state("A", T0 + timedelta(days=2)) == state_after_later
    assert "earlier" in model.pending_match_ids


def test_pending_forecast_is_frozen_while_other_results_update_state():
    model = DynamicStrengthTempoModel()
    frozen = model.predict("future", "A", "C", T0)
    before = model.snapshot()["pending"]["future"]
    model.predict("earlier", "A", "B", T0)
    model.update("earlier", 3, 0, T0 + timedelta(days=1))

    after = model.snapshot()["pending"]["future"]
    assert after == before
    assert frozen.evidence_count == 0


def test_prediction_adapts_to_vnext_latent_state():
    prediction = DynamicStrengthTempoModel().predict("m1", "A", "B", T0)
    context = MatchContext(
        match_id="m1",
        home_team_id="A",
        away_team_id="B",
        kickoff_utc=T0 + timedelta(hours=1),
        features_as_of=T0,
    )
    state = prediction.to_vnext(context)
    assert state.expected_goals == pytest.approx(
        (prediction.lambda_home, prediction.lambda_away)
    )
    assert state.uncertainty.status == "externally_supplied"


@pytest.mark.parametrize(
    "change, error",
    [
        ({"match_id": "other"}, "identity"),
        ({"home_team_id": "C"}, "identity"),
        ({"away_team_id": "C"}, "identity"),
        (
            {"features_as_of": T0 + timedelta(seconds=1)},
            "prediction cutoff",
        ),
    ],
)
def test_prediction_rejects_relabelled_vnext_context(change, error):
    prediction = DynamicStrengthTempoModel().predict("m1", "A", "B", T0)
    context = MatchContext(
        match_id="m1",
        home_team_id="A",
        away_team_id="B",
        kickoff_utc=T0 + timedelta(hours=1),
        features_as_of=T0,
    )

    with pytest.raises(ValueError, match=error):
        prediction.to_vnext(replace(context, **change))


@pytest.mark.parametrize(
    "operation, error",
    [
        (lambda m: m.predict("m", "A", "A", T0), "must differ"),
        (
            lambda m: m.predict("m", "A", "B", datetime(2026, 1, 1)),
            "timezone-aware",
        ),
        (lambda m: m.update("missing", 1, 0, T0), "before predicting"),
    ],
)
def test_invalid_inputs_are_rejected(operation, error):
    with pytest.raises(ValueError, match=error):
        operation(DynamicStrengthTempoModel())


def test_invalid_scores_ordering_and_duplicate_use_are_rejected():
    model = DynamicStrengthTempoModel()
    model.predict("m1", "A", "B", T0)
    with pytest.raises(ValueError, match="between"):
        model.update("m1", -1, 0, T0)
    with pytest.raises(ValueError, match="cannot precede"):
        model.update("m1", 1, 0, T0 - timedelta(seconds=1))
    model.predict("m2", "A", "C", T0)

    model.update("m1", 1, 0, T0)
    with pytest.raises(ValueError, match="already been recorded"):
        model.update("m1", 1, 0, T0)
    with pytest.raises(ValueError, match="already been used"):
        model.predict("m1", "A", "B", T0 + timedelta(days=1))


def test_invalid_configuration_and_hierarchy_are_rejected():
    with pytest.raises(ValueError, match="positive"):
        DynamicModelConfig(decay_half_life_days=0.0)
    with pytest.raises(ValueError, match="unknown group"):
        DynamicStrengthTempoModel(team_groups={"A": "missing"})
    with pytest.raises(ValueError, match="unsupported"):
        DynamicStrengthTempoModel.from_snapshot({"schema_version": 999})
