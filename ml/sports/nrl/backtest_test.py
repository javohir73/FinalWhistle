"""Tests for the NRL season walk-forward backtest + tuner (task 4).

Synthetic, deterministic fixtures only — no DB. A two-season round robin
between a "strong" team (always wins big) and two "weak" teams exercises
replay_seasons/evaluate_season's leak-freedom and predict-before-update
ordering without touching real fixture data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ml.sports.nrl.backtest import evaluate_season, replay_seasons, tune
from ml.sports.nrl.model import NrlParams, predict, regress_season

STRONG, WEAK_A, WEAK_B = 1, 2, 3


def _match(match_id, kickoff, home, away, score_home, score_away):
    return {
        "match_id": match_id,
        "kickoff_utc": kickoff,
        "home_team_id": home,
        "away_team_id": away,
        "score_home": score_home,
        "score_away": score_away,
    }


def _kickoff(season, day):
    return datetime(season, 3, day, tzinfo=timezone.utc)


def _two_season_fixture():
    """STRONG beats WEAK_A/WEAK_B every time, home or away, both seasons."""
    season_2024 = [
        _match(1, _kickoff(2024, 1), STRONG, WEAK_A, 30, 6),
        _match(2, _kickoff(2024, 8), WEAK_B, STRONG, 4, 28),
        _match(3, _kickoff(2024, 15), STRONG, WEAK_B, 24, 10),
        _match(4, _kickoff(2024, 22), WEAK_A, STRONG, 8, 26),
    ]
    season_2025 = [
        _match(5, _kickoff(2025, 1), STRONG, WEAK_B, 32, 4),
        _match(6, _kickoff(2025, 8), WEAK_A, STRONG, 6, 30),
        _match(7, _kickoff(2025, 15), STRONG, WEAK_A, 22, 12),
        _match(8, _kickoff(2025, 22), WEAK_B, STRONG, 10, 24),
    ]
    return {2024: season_2024, 2025: season_2025}


def test_replay_seasons_returns_elos_per_season_seeded_1500():
    matches_by_season = _two_season_fixture()
    params = NrlParams()
    elos = replay_seasons(matches_by_season, params)

    assert set(elos.keys()) == {2024, 2025}
    # STRONG should have gained rating in both seasons; WEAK teams lost.
    assert elos[2024][STRONG] > 1500
    assert elos[2024][WEAK_A] < 1500
    assert elos[2024][WEAK_B] < 1500


def test_replay_seasons_applies_regression_between_seasons():
    matches_by_season = _two_season_fixture()
    params = NrlParams()
    elos = replay_seasons(matches_by_season, params)

    # If season boundary regression were skipped, 2025 would start exactly at
    # 2024's end-of-season Elo and STRONG's rating would only move further
    # from 1500 by (roughly) the sum of 2024 and 2025 movement. Regression
    # pulls the *starting* point of 2025 back toward 1500, so end-of-season
    # 2025 rating should land closer to 1500 than the naive "no regression"
    # accumulation would.
    naive_no_regress = NrlParams(season_regress=0.0)
    elos_no_regress = replay_seasons(matches_by_season, naive_no_regress)

    assert elos[2025][STRONG] < elos_no_regress[2025][STRONG]


def test_evaluate_season_walk_forward_accuracy_favors_strong_team():
    matches_by_season = _two_season_fixture()
    params = NrlParams()
    elos_2024 = replay_seasons({2024: matches_by_season[2024]}, params)[2024]

    class_freqs = (0.5, 0.0, 0.5)  # placeholder prior; strong-team fixture has no draws
    result = evaluate_season(matches_by_season[2025], elos_2024, params, class_freqs)

    assert result["n"] == 4
    assert result["winner_acc"] > 0.5


def test_evaluate_season_does_not_mutate_elos_in():
    matches_by_season = _two_season_fixture()
    params = NrlParams()
    elos_2024 = replay_seasons({2024: matches_by_season[2024]}, params)[2024]
    snapshot = dict(elos_2024)

    class_freqs = (0.5, 0.0, 0.5)
    evaluate_season(matches_by_season[2025], elos_2024, params, class_freqs)

    assert elos_2024 == snapshot


def test_leak_freedom_season_boundary_uses_replay_not_evaluate_mutation():
    """Evaluating season N must not leak into what season N+1 receives except
    through replay_seasons' own season-boundary regression — i.e. calling
    evaluate_season on 2024 must not change the elos replay_seasons hands to
    2025."""
    matches_by_season = _two_season_fixture()
    params = NrlParams()

    elos_2024 = replay_seasons({2024: matches_by_season[2024]}, params)[2024]
    class_freqs = (0.5, 0.0, 0.5)
    evaluate_season(matches_by_season[2024], dict(elos_2024), params, class_freqs)

    full_replay = replay_seasons(matches_by_season, params)
    reference = replay_seasons({2024: matches_by_season[2024]}, params)[2024]
    assert elos_2024 == reference
    assert full_replay[2024] == reference


def test_predict_before_update_pinned_to_seed_elo():
    """The first match's recorded model probability must equal predict() from
    the seed Elo exactly — proving predict happens before update, not after."""
    matches_by_season = _two_season_fixture()
    params = NrlParams()
    seed_elos = {STRONG: 1500.0, WEAK_A: 1500.0}
    class_freqs = (0.5, 0.0, 0.5)

    first_match = matches_by_season[2024][:1]
    result = evaluate_season(first_match, seed_elos, params, class_freqs)

    expected = predict(1500.0, 1500.0, params)
    home_won = first_match[0]["score_home"] > first_match[0]["score_away"]
    idx = 0 if home_won else 2
    expected_p = [expected["p_home"], expected["p_draw"], expected["p_away"]][idx]

    # log_loss for a single match of a correctly-favored outcome is -log(p).
    import math
    assert abs(result["log_loss"] - (-math.log(expected_p))) < 1e-9


def test_evaluate_season_unseen_team_seeded_1500():
    params = NrlParams()
    class_freqs = (0.5, 0.0, 0.5)
    matches = [_match(1, _kickoff(2024, 1), 99, 100, 20, 10)]
    result = evaluate_season(matches, {}, params, class_freqs)
    assert result["n"] == 1


def test_evaluate_season_baselines_scored_on_same_matches():
    matches_by_season = _two_season_fixture()
    params = NrlParams()
    elos_2024 = replay_seasons({2024: matches_by_season[2024]}, params)[2024]
    class_freqs = (0.5, 0.0, 0.5)

    result = evaluate_season(matches_by_season[2025], elos_2024, params, class_freqs)

    assert result["favorite"]["n"] == result["n"]
    assert result["home"]["n"] == result["n"]
    assert set(result["favorite"].keys()) == {"log_loss", "brier", "winner_acc", "n"}
    assert set(result["home"].keys()) == {"log_loss", "brier", "winner_acc", "n"}


def test_evaluate_season_home_baseline_always_picks_home():
    """The home baseline uses fixed class-freq probabilities reordered so the
    home slot gets the highest mass — i.e. it "always picks home" in the
    argmax sense, regardless of actual Elo."""
    class_freqs = (0.55, 0.05, 0.40)  # home is already the largest -> reordering is a no-op signal
    matches = [_match(1, _kickoff(2024, 1), WEAK_A, STRONG, 6, 30)]  # away (STRONG) wins
    params = NrlParams()
    result = evaluate_season(matches, {WEAK_A: 1500.0, STRONG: 1500.0}, params, class_freqs)
    # home baseline predicted home with p=0.55 but away actually won -> wrong pick
    assert result["home"]["winner_acc"] == 0.0


def test_tune_returns_params_from_grid_with_val_logloss_not_worse_than_default():
    matches_by_season = _two_season_fixture()
    train_rows_by_season = {2024: matches_by_season[2024]}
    val_matches = matches_by_season[2025]

    tuned = tune(train_rows_by_season, val_matches, grid=None)

    elos_2024 = replay_seasons(train_rows_by_season, NrlParams())[2024]
    class_freqs = (0.5, 0.0, 0.5)

    default_ll = evaluate_season(val_matches, elos_2024, NrlParams(), class_freqs)["log_loss"]

    elos_2024_tuned = replay_seasons(train_rows_by_season, tuned)[2024]
    tuned_ll = evaluate_season(val_matches, elos_2024_tuned, tuned, class_freqs)["log_loss"]

    assert tuned_ll <= default_ll + 1e-9
    assert isinstance(tuned, NrlParams)


def test_tune_regresses_at_the_val_season_boundary_train_serve_parity(monkeypatch):
    """tune()'s val evaluation must enter the val season from the REGRESSED
    end-of-train-season Elo, not the raw replay_seasons snapshot -- matching
    the serving path's season-boundary regression (nrl_predict._current_elos)
    and the CLI gate's held-out entry. Pin this by intercepting the elos_in
    tune() actually hands to evaluate_season and comparing it to the
    regressed snapshot (elos differ from the raw snapshot by exactly the
    regress fraction toward 1500)."""
    matches_by_season = _two_season_fixture()
    train_rows_by_season = {2024: matches_by_season[2024]}
    val_matches = matches_by_season[2025]
    params = NrlParams()

    single_grid = {
        "k": [params.k],
        "home_adv": [params.home_adv],
        "margin_mult_cap": [params.margin_mult_cap],
        "season_regress": [params.season_regress],
        "p_draw": [params.p_draw],
    }

    captured_elos_in: list[dict[int, float]] = []
    import ml.sports.nrl.backtest as backtest_mod
    real_evaluate_season = backtest_mod.evaluate_season

    def _spy_evaluate_season(matches, elos_in, p, class_freqs):
        captured_elos_in.append(dict(elos_in))
        return real_evaluate_season(matches, elos_in, p, class_freqs)

    monkeypatch.setattr(backtest_mod, "evaluate_season", _spy_evaluate_season)

    tuned = tune(train_rows_by_season, val_matches, grid=single_grid)
    assert tuned == params  # single-value grid -> tune is a no-op on the params
    assert captured_elos_in  # tune must have called evaluate_season at least once

    raw_snapshot = replay_seasons(train_rows_by_season, params)[2024]
    regressed_snapshot = regress_season(raw_snapshot, params)
    assert raw_snapshot != regressed_snapshot  # fixture must make the two distinguishable

    used_elos_in = captured_elos_in[0]
    assert used_elos_in == regressed_snapshot
    assert used_elos_in != raw_snapshot

    # Pin the exact regression math: entry elo == raw + season_regress*(1500-raw).
    for team_id, raw_elo in raw_snapshot.items():
        expected = raw_elo + params.season_regress * (1500.0 - raw_elo)
        assert abs(used_elos_in[team_id] - expected) < 1e-9
