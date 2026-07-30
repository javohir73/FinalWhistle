"""Focused contract and parity tests for the additive vNext model core."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from ml.models.poisson import (
    expected_goals_from_elo,
    outcome_probabilities,
    predict_match,
    score_matrix,
)
from ml.models.vnext import (
    LegacyPoissonEloAdapter,
    LatentMatchState,
    MatchContext,
    NO_UNCERTAINTY,
    ScoreDistribution,
    UncertaintyMetadata,
    WinDrawLoss,
    calibrate_distribution_to_wdl,
    headline_prediction_from_distribution,
    state_from_elo_strength_and_tempo,
)


def _context(match_id: str = "test-1") -> MatchContext:
    kickoff = datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc)
    return MatchContext(
        match_id=match_id,
        home_team_id="ARG",
        away_team_id="ESP",
        kickoff_utc=kickoff,
        features_as_of=kickoff - timedelta(hours=2),
        competition_id="WC26",
        neutral_venue=True,
    )


def test_contracts_are_immutable_and_context_enforces_as_of_cutoff():
    context = _context()
    with pytest.raises(FrozenInstanceError):
        context.home_team_id = "BRA"

    state = LatentMatchState(context, 0.2, 1.0)
    with pytest.raises(FrozenInstanceError):
        state.rho = -0.08

    with pytest.raises(ValueError, match="after kickoff"):
        MatchContext(
            match_id="leaky",
            home_team_id="ARG",
            away_team_id="ESP",
            kickoff_utc=context.kickoff_utc,
            features_as_of=context.kickoff_utc + timedelta(seconds=1),
        )


def test_context_requires_timezone_aware_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        MatchContext(
            match_id="naive-time",
            home_team_id="ARG",
            away_team_id="ESP",
            features_as_of=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
            kickoff_utc=datetime(2026, 6, 12, 10, 0),
        )

    with pytest.raises(ValueError, match="features_as_of is required"):
        MatchContext(
            match_id="missing-cutoff",
            home_team_id="ARG",
            away_team_id="ESP",
            features_as_of=None,
        )


def test_strength_changes_share_but_not_total():
    low = LatentMatchState(_context(), strength_log_ratio=-1.0, log_total_goals=1.0)
    high = LatentMatchState(_context(), strength_log_ratio=1.0, log_total_goals=1.0)
    low_h, low_a = low.expected_goals
    high_h, high_a = high.expected_goals

    assert low_h + low_a == pytest.approx(high_h + high_a)
    assert low_h < low_a
    assert high_h > high_a


def test_tempo_changes_total_but_not_goal_share():
    slow = LatentMatchState(_context(), strength_log_ratio=0.7, log_total_goals=0.5)
    fast = LatentMatchState(_context(), strength_log_ratio=0.7, log_total_goals=1.5)
    slow_h, slow_a = slow.expected_goals
    fast_h, fast_a = fast.expected_goals

    assert slow_h + slow_a < fast_h + fast_a
    assert slow_h / (slow_h + slow_a) == pytest.approx(fast_h / (fast_h + fast_a))


def test_elo_strength_constructor_keeps_caller_tempo_exactly_fixed():
    weak = state_from_elo_strength_and_tempo(
        _context("weak"), 1500, 1900, total_expected_goals=2.4, beta=0.002
    )
    strong = state_from_elo_strength_and_tempo(
        _context("strong"), 2100, 1500, total_expected_goals=2.4, beta=0.002
    )
    assert sum(weak.expected_goals) == pytest.approx(2.4)
    assert sum(strong.expected_goals) == pytest.approx(2.4)
    assert weak.home_goal_share < 0.5 < strong.home_goal_share


def test_dixon_coles_distribution_is_normalized_and_immutable():
    state = LatentMatchState(_context(), 0.35, 1.0, rho=-0.08)
    distribution = ScoreDistribution.from_state(state)

    assert isinstance(distribution.grid, tuple)
    assert all(isinstance(row, tuple) for row in distribution.grid)
    assert sum(sum(row) for row in distribution.grid) == pytest.approx(1.0, abs=1e-12)
    assert all(cell >= 0.0 for row in distribution.grid for cell in row)
    with pytest.raises(TypeError):
        distribution.grid[0][0] = 0.5


def test_dixon_coles_rho_changes_grid_via_existing_score_matrix():
    context = _context()
    plain = ScoreDistribution.from_state(LatentMatchState(context, 0.0, 1.0, rho=0.0))
    dc = ScoreDistribution.from_state(LatentMatchState(context, 0.0, 1.0, rho=-0.1))
    lambda_home, lambda_away = dc.latent_expected_goals
    raw = score_matrix(lambda_home, lambda_away, rho=-0.1)
    raw_total = sum(sum(row) for row in raw)

    assert dc.grid[0][0] == pytest.approx(raw[0][0] / raw_total)
    assert dc.grid[1][1] == pytest.approx(raw[1][1] / raw_total)
    assert dc.wdl.draw > plain.wdl.draw


def test_pathological_dixon_coles_rho_fails_closed():
    state = LatentMatchState(_context(), 0.0, 1.0, rho=10.0)
    with pytest.raises(ValueError, match="invalid Dixon-Coles"):
        ScoreDistribution.from_state(state)

    # At rho=1 one Dixon-Coles multiplier is exactly zero; the boundary is
    # rejected rather than silently erasing the 1-1 cell.
    boundary = LatentMatchState(_context(), 0.0, -2.0, rho=1.0)
    with pytest.raises(ValueError, match="invalid Dixon-Coles"):
        ScoreDistribution.from_state(boundary)


def test_every_market_is_a_marginal_of_the_single_grid():
    distribution = ScoreDistribution.from_state(LatentMatchState(_context(), 0.5, 1.1, rho=-0.06))
    grid = distribution.grid
    size = len(grid)

    manual_wdl = (
        sum(grid[h][a] for h in range(size) for a in range(size) if h > a),
        sum(grid[h][a] for h in range(size) for a in range(size) if h == a),
        sum(grid[h][a] for h in range(size) for a in range(size) if h < a),
    )
    manual_over_25 = sum(
        grid[h][a] for h in range(size) for a in range(size) if h + a > 2.5
    )
    manual_btts = sum(grid[h][a] for h in range(1, size) for a in range(1, size))

    assert distribution.wdl.as_tuple() == pytest.approx(manual_wdl)
    assert sum(distribution.wdl.as_tuple()) == pytest.approx(1.0)
    assert distribution.goal_markets.over_2_5 == pytest.approx(manual_over_25)
    assert distribution.goal_markets.btts_yes == pytest.approx(manual_btts)
    assert distribution.goal_markets.btts_yes + distribution.goal_markets.btts_no == pytest.approx(
        1.0
    )
    assert sum(item.probability for item in distribution.correct_scores()) == pytest.approx(1.0)


def test_legacy_adapter_expected_goals_is_bit_identical():
    adapter = LegacyPoissonEloAdapter(base=1.2, beta=0.0021, home_advantage_elo=60.0)
    offsets = {"atk_home": 0.04, "def_home": -0.01, "atk_away": -0.02, "def_away": 0.03}
    expected = expected_goals_from_elo(1900, 1760, 60.0, 1.2, 0.0021, **offsets)
    assert adapter.expected_goals(1900, 1760, **offsets) == expected


def test_legacy_adapter_prediction_is_bit_identical_with_calibration():
    calibrator = {"method": "vector_scaling", "t": 1.1, "b": [0.02, 0.1, -0.03]}
    adapter = LegacyPoissonEloAdapter(
        base=1.2,
        beta=0.0021,
        home_advantage_elo=60.0,
        rho=-0.06,
        temperature=1.15,
        calibrator=calibrator,
    )
    offsets = {"atk_home": 0.04, "def_home": -0.01, "atk_away": -0.02, "def_away": 0.03}
    expected = predict_match(
        1900,
        1760,
        home_adv=60.0,
        base=1.2,
        beta=0.0021,
        rho=-0.06,
        temperature=1.15,
        calibrator=calibrator,
        **offsets,
    )
    assert adapter.prediction(1900, 1760, **offsets) == expected


def test_legacy_adapter_distribution_preserves_lambdas_and_raw_wdl():
    adapter = LegacyPoissonEloAdapter(
        base=1.2, beta=0.0021, home_advantage_elo=60.0, rho=-0.06
    )
    expected_lambdas = expected_goals_from_elo(1900, 1760, 60.0, 1.2, 0.0021)
    distribution = adapter.raw_distribution(_context(), 1900, 1760)
    legacy_wdl = outcome_probabilities(score_matrix(*expected_lambdas, rho=-0.06))

    assert distribution.latent_expected_goals == pytest.approx(
        expected_lambdas, rel=1e-15, abs=1e-15
    )
    assert distribution.wdl.as_tuple() == pytest.approx(legacy_wdl, rel=1e-15, abs=1e-15)


def test_legacy_shape_projection_remains_coherent_with_grid():
    distribution = ScoreDistribution.from_state(LatentMatchState(_context(), 0.7, 1.0, rho=-0.06))
    prediction = headline_prediction_from_distribution(distribution)
    assert (
        prediction.prob_home_win,
        prediction.prob_draw,
        prediction.prob_away_win,
    ) == pytest.approx(distribution.wdl.as_tuple())
    assert prediction.score_prob == distribution.exact_score_probability(
        prediction.score_home, prediction.score_away
    )


def test_coherent_wdl_calibration_identity_returns_same_distribution():
    distribution = ScoreDistribution.from_state(LatentMatchState(_context(), 0.3, 1.0))
    calibrated = calibrate_distribution_to_wdl(
        distribution,
        distribution.wdl,
        calibrator_artifact_id="walk-forward-calibrator-v1",
    )
    assert calibrated.grid == distribution.grid
    assert calibrated.calibration is not None
    assert calibrated.calibration.artifact_id == "walk-forward-calibrator-v1"


def test_coherent_wdl_calibration_hits_exact_target():
    distribution = ScoreDistribution.from_state(LatentMatchState(_context(), 0.3, 1.0))
    target = WinDrawLoss(home=0.52, draw=0.28, away=0.20)
    calibrated = distribution.calibrated_to_wdl(
        target, calibrator_artifact_id="walk-forward-calibrator-v1"
    )
    assert calibrated.wdl.as_tuple() == pytest.approx(target.as_tuple(), abs=1e-12)
    assert sum(sum(row) for row in calibrated.grid) == pytest.approx(1.0, abs=1e-12)


def test_coherent_wdl_calibration_keeps_markets_on_adjusted_grid():
    distribution = ScoreDistribution.from_state(
        LatentMatchState(_context(), 0.3, 1.0, rho=-0.06)
    )
    calibrated = distribution.calibrated_to_wdl(
        (0.50, 0.30, 0.20), calibrator_artifact_id="walk-forward-calibrator-v1"
    )
    grid = calibrated.grid
    size = len(grid)
    manual_over_25 = sum(
        grid[h][a] for h in range(size) for a in range(size) if h + a > 2.5
    )
    manual_btts = sum(grid[h][a] for h in range(1, size) for a in range(1, size))
    manual_home_mean = sum(h * grid[h][a] for h in range(size) for a in range(size))
    manual_away_mean = sum(a * grid[h][a] for h in range(size) for a in range(size))
    assert calibrated.goal_markets.over_2_5 == pytest.approx(manual_over_25)
    assert calibrated.goal_markets.btts_yes == pytest.approx(manual_btts)
    assert calibrated.expected_goals == pytest.approx((manual_home_mean, manual_away_mean))
    assert calibrated.grid_expected_goals == calibrated.expected_goals
    assert calibrated.expected_goals != pytest.approx(calibrated.latent_expected_goals, abs=1e-6)
    assert calibrated.wdl.as_tuple() == pytest.approx((0.50, 0.30, 0.20), abs=1e-12)
    with pytest.raises(ValueError, match="cannot represent a calibrated"):
        headline_prediction_from_distribution(calibrated)
    with pytest.raises(ValueError, match="already calibrated"):
        calibrated.calibrated_to_wdl(
            (0.45, 0.30, 0.25), calibrator_artifact_id="another-artifact"
        )


def test_uncertainty_is_explicitly_not_estimated_by_default():
    state = LatentMatchState(_context(), 0.0, 1.0)
    distribution = ScoreDistribution.from_state(state)
    assert distribution.uncertainty is NO_UNCERTAINTY
    assert distribution.uncertainty.status == "not_estimated"
    assert distribution.uncertainty.strength_std is None
    assert distribution.uncertainty.log_total_goals_std is None
    assert distribution.uncertainty.strength_tempo_correlation is None

    with pytest.raises(ValueError, match="cannot contain estimates"):
        UncertaintyMetadata(status="not_estimated", strength_std=0.1)

    supplied = UncertaintyMetadata(
        status="externally_supplied",
        strength_std=0.1,
        log_total_goals_std=0.08,
        strength_tempo_correlation=-0.2,
        source="walk-forward bootstrap run 42",
        sample_count=500,
    )
    assert supplied.status == "externally_supplied"

    with pytest.raises(ValueError, match="requires both"):
        UncertaintyMetadata(
            status="externally_supplied",
            strength_std=0.1,
            strength_tempo_correlation=0.2,
            source="incomplete fit",
        )


def test_model_version_fits_existing_persistence_contract():
    assert len(LegacyPoissonEloAdapter().model_version) <= 40
    with pytest.raises(ValueError, match="40-character"):
        LatentMatchState(_context(), 0.0, 1.0, model_version="x" * 41)
