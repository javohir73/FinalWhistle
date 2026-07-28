from datetime import datetime, timedelta, timezone

import pytest

from ml.evaluation.market_benchmark import InPlayObservation, benchmark_inplay, inplay_horizon

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


@pytest.mark.parametrize("minute,period,expected", [
    (0, "first_half", "0-15"), (14.999, "first_half", "0-15"),
    (15, "first_half", "15-30"), (30, "first_half", "30-45"),
    (45, "second_half", "45-60"), (60, "second_half", "60-75"),
    (75, "second_half", "75-90"), (90, "second_half", "75-90"),
    (45, "half_time", "halftime"), (91, "extra_time", None),
])
def test_horizon_boundaries(minute, period, expected):
    assert inplay_horizon(minute, period) == expected


def observation(match_id=1, **overrides):
    values = dict(
        match_id=match_id, venue="kalshi", market_type="match_winner", minute=20,
        period="first_half", model_probs=(.6, .2, .2), venue_probs=(.5, .3, .2),
        label=0, tick_ts=NOW, model_state_ts=NOW, quote_source_ts=NOW,
        model_score=(0, 0), venue_score=(0, 0), competition="World Cup",
    )
    values.update(overrides)
    return InPlayObservation(**values)


def test_state_quality_exclusions_are_counted_not_silently_dropped():
    rows = [
        observation(),
        observation(2, mapping_status="ambiguous"),
        observation(3, model_score=(1, 0)),
        observation(7, model_cards=(1, 0)),
        observation(4, quote_source_ts=NOW - timedelta(minutes=2)),
        observation(5, settled_at=NOW),
        observation(6, supported=False),
    ]
    report = benchmark_inplay(rows, held_out_cutoff=NOW - timedelta(days=1), minimum_matches=1, n_bootstrap=50)
    assert report["population"]["included_observations"] == 1
    assert report["population"]["exclusions"] == {
        "card_state_mismatch": 1,
        "post_settlement_tick": 1,
        "score_state_mismatch": 1,
        "stale_or_missing_quote_time": 1,
        "unresolved_mapping": 1,
        "unsupported_outcome": 1,
    }


def test_venue_market_type_and_horizon_never_pool():
    rows = [
        observation(1),
        observation(2, venue="polymarket"),
        observation(3, market_type="btts", model_probs=(.6, .4), venue_probs=(.5, .5), label=1),
        observation(4, minute=50, period="second_half"),
    ]
    report = benchmark_inplay(rows, held_out_cutoff=NOW - timedelta(days=1), minimum_matches=1, n_bootstrap=50)
    keys = {(g["venue"], g["market_type"], g["horizon"]) for g in report["groups"]}
    assert keys == {
        ("kalshi", "match_winner", "15-30"),
        ("polymarket", "match_winner", "15-30"),
        ("kalshi", "btts", "15-30"),
        ("kalshi", "match_winner", "45-60"),
    }


def test_match_clustered_bootstrap_carries_correlated_ticks_together():
    # One match contributes 100 model-favouring ticks; the other contributes a
    # single market-favouring tick. Treating 101 ticks as independent would make
    # the first match look falsely decisive. Match resampling retains the split.
    rows = [observation(1, model_probs=(.8, .1, .1), venue_probs=(.6, .2, .2)) for _ in range(100)]
    rows.append(observation(2, model_probs=(.1, .8, .1), venue_probs=(.9, .05, .05)))
    report = benchmark_inplay(rows, held_out_cutoff=NOW - timedelta(days=1), minimum_matches=2, n_bootstrap=1000, seed=7)
    group = report["groups"][0]
    assert group["paired_ticks"] == 101 and group["sample_matches"] == 2
    assert group["diff_ci95"][0] < 0 < group["diff_ci95"][1]
    assert group["verdict"] == "inconclusive"


def test_output_is_deterministic_and_insufficient_is_honest():
    rows = [observation(1), observation(2)]
    first = benchmark_inplay(rows, held_out_cutoff=NOW - timedelta(days=1), minimum_matches=5, n_bootstrap=50)
    second = benchmark_inplay(rows, held_out_cutoff=NOW - timedelta(days=1), minimum_matches=5, n_bootstrap=50)
    assert first == second
    assert first["groups"][0]["status"] == "insufficient"
    assert first["groups"][0]["verdict"] == "insufficient"
