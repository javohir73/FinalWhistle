"""NRL season walk-forward backtest + coordinate-descent tuner (task 4).

Two leak-free passes, mirroring ml/evaluation/backtest.py's replay/evaluate
split but at season granularity (NRL has no data before 2017, so a per-season
walk-forward — rather than a single rolling window — is the natural unit):

  replay_seasons  — advances Elo across whole seasons, in kickoff order,
                     applying `regress_season` at each season boundary. Used
                     to produce the leak-free starting ratings for a held-out
                     season (train on everything strictly before it).
  evaluate_season — walk-forward WITHIN one season: predict each match from
                     the ratings as they stand, record metrics, THEN update —
                     never the other order, or a match's own result would
                     leak into its own prediction.

`tune` coordinate-descents the W/D/L-relevant knobs (k, home_adv,
margin_mult_cap, season_regress, p_draw) against evaluate_season's model log
loss on a single held-out validation season, mirroring ml/evaluation/tune.py's
style. margin_slope/margin_sigma are left at their defaults — they only feed
expected_margin, which doesn't enter the 3-way log loss this objective scores.
"""
from __future__ import annotations

import math
from dataclasses import replace

from ml.sports.nrl.model import NrlParams, predict, regress_season, update

_EPS = 1e-15
SEED_ELO = 1500.0

# Coordinate-descent grids (W/D/L-relevant knobs only).
_K_GRID = [24.0, 32.0, 36.0, 44.0]
_HOME_ADV_GRID = [25.0, 45.0, 65.0]
_MARGIN_CAP_GRID = [1.8, 2.2, 2.6]
_SEASON_REGRESS_GRID = [0.15, 0.25, 0.35]
_P_DRAW_GRID = [0.008, 0.012, 0.02]


def _elo_for(elos: dict[int, float], team_id: int) -> float:
    """Current rating for `team_id`, seeded at SEED_ELO on first sight."""
    return elos.get(team_id, SEED_ELO)


def replay_seasons(
    matches_by_season: dict[int, list[dict]], params: NrlParams
) -> dict[int, dict[int, float]]:
    """End-of-season Elo per team, one snapshot per season.

    Seasons are walked in order; within a season, matches are processed in
    kickoff order (leak-free — each match updates from ratings that reflect
    only earlier matches). `regress_season` is applied to the running ratings
    at each season boundary, so a season's matches see the REGRESSED ratings
    from the previous season, but the snapshot recorded for that season is
    its own end-of-season (post-update, pre-next-boundary-regression) state.
    """
    running: dict[int, float] = {}
    snapshots: dict[int, dict[int, float]] = {}

    for season in sorted(matches_by_season):
        running = regress_season(running, params) if running else running
        matches = sorted(matches_by_season[season], key=lambda m: m["kickoff_utc"])
        for m in matches:
            home_id, away_id = m["home_team_id"], m["away_team_id"]
            elo_home = _elo_for(running, home_id)
            elo_away = _elo_for(running, away_id)
            new_home, new_away = update(elo_home, elo_away, m["score_home"], m["score_away"], params)
            running[home_id] = new_home
            running[away_id] = new_away
        snapshots[season] = dict(running)

    return snapshots


def _result_index(score_home: int, score_away: int) -> int:
    """0=home, 1=draw, 2=away."""
    if score_home > score_away:
        return 0
    if score_home < score_away:
        return 2
    return 1


def _clamp(p: float) -> float:
    return max(_EPS, min(1 - _EPS, p))


def _score(probs: tuple[float, float, float], idx: int) -> tuple[float, float, bool]:
    """(log_loss contribution, brier contribution, winner-correct) for one match."""
    p = [_clamp(x) for x in probs]
    ll = -math.log(p[idx])
    brier = sum((p[k] - (1.0 if k == idx else 0.0)) ** 2 for k in range(3))
    predicted_idx = max(range(3), key=lambda k: probs[k])
    correct = predicted_idx == idx
    return ll, brier, correct


def _finalize(ll_sum: float, brier_sum: float, correct_sum: int, n: int) -> dict:
    if n == 0:
        return {"log_loss": float("nan"), "brier": float("nan"), "winner_acc": float("nan"), "n": 0}
    return {
        "log_loss": ll_sum / n,
        "brier": brier_sum / n,
        "winner_acc": correct_sum / n,
        "n": n,
    }


def evaluate_season(
    matches: list[dict],
    elos_in: dict[int, float],
    params: NrlParams,
    class_freqs: tuple[float, float, float],
) -> dict:
    """Walk-forward evaluation of one season's finished matches.

    For each match in kickoff order: predict from the CURRENT state (unseen
    team ids seeded at SEED_ELO), score the model AND the two baselines on
    that same match, then update the model's running Elo. `elos_in` is never
    mutated — a fresh copy is used internally, so callers can safely reuse
    the dict they pass in for a later season.

    Baselines, both evaluated on the identical match list as the model:
      favorite — picks the higher pre-match Elo (home rating includes
                 home_adv, mirroring how `predict` itself applies it);
                 probabilities are `class_freqs` (prior seasons' outcome
                 frequencies), reordered so the largest mass sits on
                 whichever side (home/away) is favored.
      home     — always favors home; probabilities are `class_freqs` with
                 the home slot forced to the largest mass (i.e. reordered
                 exactly like `favorite` would for an always-home pick).
    """
    running = dict(elos_in)
    matches = sorted(matches, key=lambda m: m["kickoff_utc"])

    model_ll = model_brier = 0.0
    model_correct = 0
    fav_ll = fav_brier = 0.0
    fav_correct = 0
    home_ll = home_brier = 0.0
    home_correct = 0

    home_freq, draw_freq, away_freq = class_freqs
    home_away_sorted = sorted((home_freq, away_freq), reverse=True)  # [larger, smaller]

    def _reordered_for_favorite(idx_favored: int) -> tuple[float, float, float]:
        """class_freqs with the draw slot (index 1) kept as-is and the
        larger of the home/away masses placed on idx_favored — i.e. only
        home vs away is reordered by who's favored; the draw prior is never
        moved, since neither baseline ever "picks" a draw."""
        larger, smaller = home_away_sorted
        probs = [0.0, draw_freq, 0.0]
        probs[idx_favored] = larger
        other = 0 if idx_favored == 2 else 2
        probs[other] = smaller
        return tuple(probs)

    for m in matches:
        home_id, away_id = m["home_team_id"], m["away_team_id"]
        elo_home = _elo_for(running, home_id)
        elo_away = _elo_for(running, away_id)

        idx = _result_index(m["score_home"], m["score_away"])

        model_p = predict(elo_home, elo_away, params)
        ll, brier, correct = _score(
            (model_p["p_home"], model_p["p_draw"], model_p["p_away"]), idx
        )
        model_ll += ll
        model_brier += brier
        model_correct += int(correct)

        fav_idx = 0 if (elo_home + params.home_adv) >= elo_away else 2
        fav_p = _reordered_for_favorite(fav_idx)
        ll, brier, correct = _score(fav_p, idx)
        fav_ll += ll
        fav_brier += brier
        fav_correct += int(correct)

        home_p = _reordered_for_favorite(0)
        ll, brier, correct = _score(home_p, idx)
        home_ll += ll
        home_brier += brier
        home_correct += int(correct)

        new_home, new_away = update(elo_home, elo_away, m["score_home"], m["score_away"], params)
        running[home_id] = new_home
        running[away_id] = new_away

    n = len(matches)
    return {
        **_finalize(model_ll, model_brier, model_correct, n),
        "favorite": _finalize(fav_ll, fav_brier, fav_correct, n),
        "home": _finalize(home_ll, home_brier, home_correct, n),
    }


def class_freqs_from_matches(matches: list[dict]) -> tuple[float, float, float]:
    """Outcome class frequencies (home, draw, away) across `matches`."""
    n = len(matches)
    if n == 0:
        return (1 / 3, 1 / 3, 1 / 3)
    counts = [0, 0, 0]
    for m in matches:
        counts[_result_index(m["score_home"], m["score_away"])] += 1
    return tuple(c / n for c in counts)


def tune(
    train_rows_by_season: dict[int, list[dict]],
    val_season_matches: list[dict],
    grid: dict | None = None,
) -> NrlParams:
    """Coordinate-descent the W/D/L-relevant NrlParams knobs on val log loss.

    `train_rows_by_season` is replayed (leak-free) to produce the Elo state
    the validation season starts from; margin_slope/margin_sigma stay at
    NrlParams defaults throughout since they don't feed the W/D/L objective.
    `grid` optionally overrides the built-in search grids (mainly for tests);
    keys: "k", "home_adv", "margin_mult_cap", "season_regress", "p_draw".
    """
    g = grid or {}
    k_grid = g.get("k", _K_GRID)
    home_adv_grid = g.get("home_adv", _HOME_ADV_GRID)
    margin_cap_grid = g.get("margin_mult_cap", _MARGIN_CAP_GRID)
    season_regress_grid = g.get("season_regress", _SEASON_REGRESS_GRID)
    p_draw_grid = g.get("p_draw", _P_DRAW_GRID)

    class_freqs = class_freqs_from_matches(
        [m for matches in train_rows_by_season.values() for m in matches]
    )

    def val_logloss(p: NrlParams) -> float:
        elos_in = replay_seasons(train_rows_by_season, p)
        last_train_season = max(train_rows_by_season) if train_rows_by_season else None
        end_of_train = elos_in.get(last_train_season, {}) if last_train_season is not None else {}
        # replay_seasons' snapshots are end-of-season, pre-boundary-regression
        # for the NEXT season -- regress here so the val season is entered
        # with the same composition the serving path uses at a season
        # boundary (pipeline.sports.nrl_predict._current_elos).
        starting_elos = regress_season(end_of_train, p) if end_of_train else end_of_train
        return evaluate_season(val_season_matches, starting_elos, p, class_freqs)["log_loss"]

    params = NrlParams()

    def best_on(grid_vals, field):
        best_v, best_ll = getattr(params, field), float("inf")
        for v in grid_vals:
            candidate = replace(params, **{field: v})
            ll = val_logloss(candidate)
            if ll < best_ll:
                best_ll, best_v = ll, v
        return best_v

    for _ in range(2):
        params = replace(params, k=best_on(k_grid, "k"))
        params = replace(params, home_adv=best_on(home_adv_grid, "home_adv"))
        params = replace(params, margin_mult_cap=best_on(margin_cap_grid, "margin_mult_cap"))
        params = replace(params, season_regress=best_on(season_regress_grid, "season_regress"))
        params = replace(params, p_draw=best_on(p_draw_grid, "p_draw"))

    return params
