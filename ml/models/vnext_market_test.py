"""Tests for latent-space market inversion and blending."""
import math
from datetime import datetime, timedelta, timezone

import pytest

from ml.models.poisson import poisson_pmf
from ml.models.vnext import (
    FixtureIdentity,
    LatentMatchState,
    MatchContext,
    NO_UNCERTAINTY,
    ScoreDistribution,
    StateProvenance,
    UncertaintyMetadata,
)
from ml.models.vnext_market import (
    MarketEvidence,
    blend_fundamental_and_market,
    market_latent_state,
)


def _context() -> MatchContext:
    kickoff = datetime(2026, 6, 15, tzinfo=timezone.utc)
    return MatchContext(
        match_id="market-1",
        home_team_id="ARG",
        away_team_id="ESP",
        kickoff_utc=kickoff,
        features_as_of=kickoff - timedelta(hours=1),
    )


def _evidence(
    wdl=(0.55, 0.25, 0.20),
    *,
    over_2_5=None,
    context: MatchContext | None = None,
    fixture: FixtureIdentity | None = None,
    captured_at: datetime | None = None,
    known_at: datetime | None = None,
) -> MarketEvidence:
    context = context or _context()
    return MarketEvidence(
        fixture=fixture or context.fixture_identity,
        captured_at=captured_at or context.features_as_of - timedelta(minutes=10),
        known_at=known_at or context.features_as_of - timedelta(minutes=5),
        wdl=wdl,
        artifact_id="consensus-snapshot-1",
        over_2_5=over_2_5,
    )


def test_market_state_uses_ou_for_tempo_and_1x2_for_strength():
    total = 2.4
    p_over = 1.0 - sum(poisson_pmf(k, total) for k in range(3))
    evidence = _evidence(over_2_5=p_over)

    state = market_latent_state(_context(), evidence)
    distribution = ScoreDistribution.from_state(state)

    assert state.total_expected_goals == pytest.approx(total, abs=1e-10)
    assert distribution.wdl.home - distribution.wdl.away == pytest.approx(0.35, abs=1e-9)
    assert [(item.source, item.artifact_id) for item in state.provenance] == [
        ("market-consensus", "consensus-snapshot-1")
    ]
    assert distribution.provenance == state.provenance


def test_decimal_prices_are_devigged_and_require_complete_total_market():
    evidence = MarketEvidence.from_decimal_odds(
        1.8,
        3.8,
        5.0,
        odds_over_2_5=1.9,
        odds_under_2_5=2.0,
        fixture=_context().fixture_identity,
        captured_at=_context().features_as_of - timedelta(minutes=10),
        known_at=_context().features_as_of - timedelta(minutes=5),
        artifact_id="decimal-snapshot-1",
    )
    assert sum(evidence.wdl) == pytest.approx(1.0)
    assert 0.0 < evidence.over_2_5 < 1.0

    with pytest.raises(ValueError, match="supplied together"):
        MarketEvidence.from_decimal_odds(
            1.8,
            3.8,
            5.0,
            odds_over_2_5=1.9,
            fixture=_context().fixture_identity,
            captured_at=_context().features_as_of - timedelta(minutes=10),
            known_at=_context().features_as_of - timedelta(minutes=5),
            artifact_id="decimal-snapshot-2",
        )


def test_1x2_only_inversion_matches_all_three_probabilities_with_dc_rho():
    evidence = _evidence(wdl=(0.48, 0.29, 0.23))

    state = market_latent_state(_context(), evidence, rho=-0.06)
    distribution = ScoreDistribution.from_state(state)

    assert distribution.wdl.as_tuple() == pytest.approx(evidence.wdl, abs=2e-6)


def test_latent_blend_keeps_strength_and_tempo_weights_independent():
    context = _context()
    fundamental = LatentMatchState(context, strength_log_ratio=0.2, log_total_goals=math.log(2.2))
    market = LatentMatchState(context, strength_log_ratio=1.0, log_total_goals=math.log(3.2))

    tempo_only = blend_fundamental_and_market(
        fundamental, market, strength_weight=0.0, tempo_weight=0.5
    )
    strength_only = blend_fundamental_and_market(
        fundamental, market, strength_weight=0.5, tempo_weight=0.0
    )

    assert tempo_only.strength_log_ratio == fundamental.strength_log_ratio
    assert tempo_only.log_total_goals != fundamental.log_total_goals
    assert strength_only.log_total_goals == fundamental.log_total_goals
    assert strength_only.strength_log_ratio != fundamental.strength_log_ratio


def test_blend_identity_and_full_market_endpoints_are_exact():
    context = _context()
    fundamental_marker = StateProvenance(
        source="fundamental",
        artifact_id="fundamental-fit",
        effective_at=context.features_as_of - timedelta(days=1),
        known_at=context.features_as_of - timedelta(days=1),
    )
    fundamental = LatentMatchState(
        context,
        0.2,
        math.log(2.2),
        rho=-0.06,
        provenance=(fundamental_marker,),
    )
    marker = StateProvenance(
        source="market-consensus",
        artifact_id="endpoint-snapshot",
        effective_at=context.features_as_of - timedelta(minutes=10),
        known_at=context.features_as_of - timedelta(minutes=5),
    )
    market = LatentMatchState(
        context,
        0.8,
        math.log(3.0),
        rho=-0.06,
        provenance=(marker,),
    )

    identity = blend_fundamental_and_market(
        fundamental, market, strength_weight=0.0, tempo_weight=0.0
    )
    full = blend_fundamental_and_market(
        fundamental, market, strength_weight=1.0, tempo_weight=1.0
    )
    assert identity.expected_goals == pytest.approx(fundamental.expected_goals)
    assert identity.rho == fundamental.rho
    assert identity.uncertainty == fundamental.uncertainty
    assert identity.provenance == fundamental.provenance
    assert full.expected_goals == pytest.approx(market.expected_goals)
    assert full.rho == market.rho
    full_distribution = ScoreDistribution.from_state(full)
    market_distribution = ScoreDistribution.from_state(market)
    assert full_distribution.grid == market_distribution.grid
    assert full_distribution.wdl.as_tuple() == pytest.approx(
        market_distribution.wdl.as_tuple(), abs=1e-15
    )
    assert full.provenance == market.provenance


def test_blend_endpoints_carry_distinct_uncertainty_and_a_partial_blend_drops_it():
    context = _context()
    fundamental_uncertainty = UncertaintyMetadata(
        status="externally_supplied",
        strength_std=0.12,
        log_total_goals_std=0.09,
        source="walk-forward bootstrap run 7",
        sample_count=400,
    )
    market_uncertainty = UncertaintyMetadata(
        status="externally_supplied",
        strength_std=0.04,
        log_total_goals_std=0.03,
        source="closing-line dispersion",
        sample_count=12,
    )
    fundamental = LatentMatchState(
        context, 0.2, math.log(2.2), rho=-0.06, uncertainty=fundamental_uncertainty
    )
    market = LatentMatchState(
        context, 0.8, math.log(3.0), rho=-0.06, uncertainty=market_uncertainty
    )

    identity = blend_fundamental_and_market(
        fundamental, market, strength_weight=0.0, tempo_weight=0.0
    )
    full = blend_fundamental_and_market(
        fundamental, market, strength_weight=1.0, tempo_weight=1.0
    )
    partial = blend_fundamental_and_market(
        fundamental, market, strength_weight=0.5, tempo_weight=1.0
    )

    assert identity.uncertainty is fundamental_uncertainty
    assert full.uncertainty is market_uncertainty
    # Anything between the endpoints has no honest combined uncertainty, so it is
    # explicitly unestimated rather than inherited from either side.
    assert partial.uncertainty is NO_UNCERTAINTY


def test_market_evidence_rejects_wrong_fixture_and_post_cutoff_times():
    context = _context()
    wrong_fixture = FixtureIdentity("another-match", "ARG", "ESP")
    with pytest.raises(ValueError, match="fixture"):
        market_latent_state(context, _evidence(context=context, fixture=wrong_fixture))

    with pytest.raises(ValueError, match="known_at.*cutoff"):
        market_latent_state(
            context,
            _evidence(context=context, known_at=context.features_as_of + timedelta(seconds=1)),
        )
    with pytest.raises(ValueError, match="captured_at.*cutoff"):
        market_latent_state(
            context,
            _evidence(
                context=context,
                captured_at=context.features_as_of + timedelta(seconds=1),
                known_at=context.features_as_of + timedelta(seconds=2),
            ),
        )


def test_market_evidence_requires_aware_capture_and_known_times():
    context = _context()
    with pytest.raises(ValueError, match="captured_at"):
        MarketEvidence(
            fixture=context.fixture_identity,
            captured_at=datetime(2026, 1, 1),
            known_at=context.features_as_of,
            wdl=(0.5, 0.3, 0.2),
            artifact_id="naive-snapshot",
        )
    with pytest.raises(ValueError, match="before captured_at"):
        MarketEvidence(
            fixture=context.fixture_identity,
            captured_at=context.features_as_of,
            known_at=context.features_as_of - timedelta(seconds=1),
            wdl=(0.5, 0.3, 0.2),
            artifact_id="reversed-time-snapshot",
        )

    no_kickoff = MatchContext(
        match_id=context.match_id,
        home_team_id=context.home_team_id,
        away_team_id=context.away_team_id,
        features_as_of=context.features_as_of,
    )
    with pytest.raises(ValueError, match="kickoff_utc"):
        market_latent_state(no_kickoff, _evidence(context=no_kickoff))


def test_blend_rejects_rho_mismatch_instead_of_mixing_distributions():
    context = _context()
    fundamental = LatentMatchState(context, 0.2, math.log(2.2), rho=-0.06)
    market = LatentMatchState(context, 0.8, math.log(3.0), rho=0.0)
    with pytest.raises(ValueError, match="rho must match"):
        blend_fundamental_and_market(
            fundamental,
            market,
            strength_weight=1.0,
            tempo_weight=1.0,
        )


def test_invalid_market_inputs_and_weights_fail_closed():
    with pytest.raises(ValueError, match="finite"):
        _evidence(wdl=(float("nan"), 0.3, 0.7))
    with pytest.raises(ValueError, match="strictly"):
        _evidence(wdl=(0.5, 0.3, 0.2), over_2_5=1.0)
    with pytest.raises(ValueError, match="not representable"):
        market_latent_state(_context(), _evidence(wdl=(0.45, 0.10, 0.45)))

    context = _context()
    state = LatentMatchState(context, 0.0, math.log(2.5))
    with pytest.raises(ValueError, match="within"):
        blend_fundamental_and_market(
            state, state, strength_weight=1.1, tempo_weight=0.0
        )
