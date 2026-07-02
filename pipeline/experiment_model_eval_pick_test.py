"""Tests for the pick-policy gate (FR-3.1/3.2): same engine, different picks."""
from datetime import date

from ml.models.params import DEFAULT_PARAMS
from ml.models.poisson import expected_goals_from_elo, outcome_probabilities, score_matrix
from pipeline.experiment_model_eval import (
    PICK_CANDIDATES,
    knockout_flags,
    make_band_pick,
    make_empirical_pick,
    make_stage_pick,
    pick_control,
    pick_unrestricted_argmax,
    run_pick_policy,
)
from ml.evaluation.scoreline_metrics import production_scoreline_pick


def _hist_row(d, ph, pa, sh, sa, comp="Friendly", home_id=1, away_id=2):
    return {"date": d, "pre_home": ph, "pre_away": pa, "score_home": sh,
            "score_away": sa, "competition": comp, "is_neutral": True,
            "home_id": home_id, "away_id": away_id}


_CUTOFF = date(2022, 11, 20)


# --- control + band candidates -------------------------------------------------

def test_control_pick_is_exactly_the_production_rule():
    # The control candidate must delegate to the same pick production publishes
    # (harness parity, FR-2.5) — for favored AND coin-flip matchups.
    picker = pick_control([], _CUTOFF)
    for elo_home, elo_away in ((1700.0, 1400.0), (1500.0, 1500.0), (1400.0, 1700.0)):
        grid = score_matrix(*expected_goals_from_elo(elo_home, elo_away))
        wdl = outcome_probabilities(grid)
        assert picker({}, grid, wdl, False) == production_scoreline_pick(grid, *wdl)


def test_band_variants_widen_the_coinflip_window():
    # p_home - p_away = 0.12: outside the production band (0.08) but inside 0.15+.
    # Grid modal cell is the draw 1-1; the home-restricted modal is 1-0.
    grid = [
        [0.05, 0.05, 0.02],
        [0.20, 0.30, 0.03],
        [0.15, 0.10, 0.10],
    ]
    wdl = (0.45, 0.22, 0.33)
    assert pick_control([], _CUTOFF)({}, grid, wdl, False) == (1, 0)
    assert make_band_pick(0.15)([], _CUTOFF)({}, grid, wdl, False) == (1, 1)
    assert make_band_pick(0.20)([], _CUTOFF)({}, grid, wdl, False) == (1, 1)
    assert make_band_pick(0.25)([], _CUTOFF)({}, grid, wdl, False) == (1, 1)


def test_unrestricted_argmax_ignores_the_outcome_restriction():
    grid = [
        [0.05, 0.05, 0.02],
        [0.20, 0.30, 0.03],
        [0.15, 0.10, 0.10],
    ]
    wdl = (0.60, 0.15, 0.25)  # clear home favorite; control would restrict to 1-0
    assert pick_unrestricted_argmax([], _CUTOFF)({}, grid, wdl, False) == (1, 1)


# --- empirical blend candidates --------------------------------------------------

def test_empirical_blend_shifts_the_argmax_toward_history():
    # Grid narrowly prefers 1-0 over 2-0; history at this gap bucket is all 2-0.
    # With w=0.3 the blend must flip the pick to 2-0; with no usable history the
    # pick degrades to the grid argmax (1-0).
    grid = [[0.0] * 3 for _ in range(3)]
    grid[1][0] = 0.30
    grid[2][0] = 0.29
    history = [_hist_row(date(2015 + i % 5, 3, 1), 1600, 1500, 2, 0) for i in range(40)]
    match = {"pre_home": 1600.0, "pre_away": 1500.0}

    with_history = make_empirical_pick(0.3)(history, _CUTOFF)
    assert with_history(match, grid, (0.7, 0.2, 0.1), False) == (2, 0)

    no_history = make_empirical_pick(0.3)([], _CUTOFF)
    assert no_history(match, grid, (0.7, 0.2, 0.1), False) == (1, 0)


def test_empirical_blend_maps_the_table_back_to_an_away_favorite():
    # Same 2-0-favorite history; the test match's favorite is the AWAY side, so
    # the empirical cell (fav 2, dog 0) must land on the home-away cell (0, 2).
    grid = [[0.0] * 3 for _ in range(3)]
    grid[0][1] = 0.30
    grid[0][2] = 0.29
    history = [_hist_row(date(2015 + i % 5, 3, 1), 1600, 1500, 2, 0) for i in range(40)]
    picker = make_empirical_pick(0.3)(history, _CUTOFF)
    assert picker({"pre_home": 1500.0, "pre_away": 1600.0}, grid, (0.1, 0.2, 0.7), False) == (0, 2)


def test_empirical_pick_cannot_see_history_on_or_after_the_edition():
    # Belt and braces: even if the harness handed the factory rows from the
    # edition itself, the fit's strictly-before filter must drop them.
    grid = [[0.0] * 3 for _ in range(3)]
    grid[1][0] = 0.30
    grid[2][0] = 0.29
    leaked = [_hist_row(_CUTOFF, 1600, 1500, 2, 0) for _ in range(40)]
    picker = make_empirical_pick(0.3)(leaked, _CUTOFF)
    assert picker({"pre_home": 1600.0, "pre_away": 1500.0}, grid, (0.7, 0.2, 0.1), False) == (1, 0)


# --- stage inference + stage-conditional tables ----------------------------------

def test_knockout_flags_label_the_trailing_bracket_of_major_finals():
    # A 32-team World Cup edition: 48 group matches then 16 knockout matches
    # (R16+QF+SF+3rd+final). The last 16 by date must be flagged; friendlies never.
    rows = []
    for i in range(48):
        rows.append(_hist_row(date(2022, 11, 15 + i % 12), 1600, 1500, 1, 0,
                              comp="FIFA World Cup", home_id=1 + i % 32, away_id=1 + (i + 7) % 32))
    for i in range(16):
        rows.append(_hist_row(date(2022, 12, 3 + i), 1600, 1500, 2, 0,
                              comp="FIFA World Cup", home_id=1 + i % 16, away_id=17 + i % 16))
    rows.append(_hist_row(date(2022, 12, 30), 1600, 1500, 4, 4, comp="Friendly"))

    flags = knockout_flags(rows)
    assert flags[:48] == [False] * 48
    assert flags[48:64] == [True] * 16
    assert flags[64] is False


def test_stage_conditional_pick_uses_the_right_table():
    # One 8-team major edition -> the last 4 matches are knockout. Group games
    # all end 3-0 (favorite), knockouts all 0-0. On a flat grid the empirical
    # term decides: a group match picks 3-0, a knockout picks 0-0.
    hist = []
    for i in range(12):
        hist.append(_hist_row(date(2021, 6, 1 + i), 1600, 1500, 3, 0,
                              comp="Copa America", home_id=1 + i % 8, away_id=1 + (i + 3) % 8))
    for i in range(4):
        hist.append(_hist_row(date(2021, 6, 20 + i), 1600, 1500, 0, 0,
                              comp="Copa America", home_id=1 + i, away_id=5 + i))

    flat = [[1.0 / 16.0] * 4 for _ in range(4)]
    picker = make_stage_pick(0.3)(hist, _CUTOFF)
    match = {"pre_home": 1600.0, "pre_away": 1500.0}
    assert picker(match, flat, (0.4, 0.3, 0.3), False) == (3, 0)
    assert picker(match, flat, (0.4, 0.3, 0.3), True) == (0, 0)


# --- the walk-forward gate --------------------------------------------------------

def _gate_rows():
    """Two WC editions; only 2018 has a populated validation window (same shape
    as the run() harness tests), so the scored holdout is exactly its matches."""
    rows = []
    for yr in (2014, 2018):
        for i in range(120):
            rows += [
                _hist_row(date(yr, 6, 1 + i % 20), 1700, 1400, 2, 0,
                          comp="FIFA World Cup", home_id=1 + i % 16, away_id=17 + i % 16),
                _hist_row(date(yr, 6, 1 + i % 20), 1500, 1500, 1, 1,
                          comp="FIFA World Cup", home_id=1 + i % 16, away_id=17 + i % 16),
            ]
    return rows


def test_run_pick_policy_reports_every_candidate_with_gate_fields():
    res = run_pick_policy(_gate_rows(), since_year=2010, n_boot=50, val_days=3650,
                          served_params=DEFAULT_PARAMS)
    assert set(res["top1"]) == set(PICK_CANDIDATES)
    assert res["matches"] == 240  # the 2014 edition is skipped (underpowered window)
    assert res["editions"] == 1
    assert 0.0 <= res["ko_share"] <= 1.0
    control = "control (production rule)"
    assert control not in res["bootstrap"]
    for name, b in res["bootstrap"].items():
        assert set(b) >= {"d_top1", "t1_ci", "verdict"}
        lo, hi = b["t1_ci"]
        assert lo <= hi
        assert b["verdict"] in ("SHIP", "ns", "worse")


def test_run_pick_policy_honors_served_params():
    res = run_pick_policy(_gate_rows(), since_year=2010, n_boot=50, val_days=3650,
                          served_params=DEFAULT_PARAMS)
    assert res["served_version"] == DEFAULT_PARAMS.version
