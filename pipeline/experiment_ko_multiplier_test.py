"""Tests for the stage-conditional knockout lambda-multiplier gate (FR-4.7).

The historical dataset carries no stage column, so knockout matches are
inferred structurally: within an edition, the modal per-team match count is
the group-stage length; a match where BOTH sides have already played that
many games belongs to the knockout bracket. The gate then scores fixed
multipliers (0.85/0.90/0.95 on both KO lambdas) against the served engine on
knockout matches only, with the harness's edition-clustered bootstrap.
"""
from datetime import date, timedelta

from pipeline.experiment_model_eval import (
    infer_knockout_flags,
    run_ko_multiplier_gate,
    wdl_and_grid,
)
from ml.models.params import DEFAULT_PARAMS


def _edition(year: int, comp: str = "FIFA World Cup") -> list[dict]:
    """A miniature 8-team edition: two groups of 4 (3 games each), then
    semi-finals and a final — 14 matches, the last 3 being knockout."""
    d = date(year, 6, 1)
    rows = []

    def row(h, a, sh, sa, day):
        return {
            "home_id": h, "away_id": a, "pre_home": 1700.0 - 10 * h,
            "pre_away": 1700.0 - 10 * a, "is_neutral": True,
            "competition": comp, "score_home": sh, "score_away": sa,
            "date": d + timedelta(days=day),
        }

    day = 0
    for group in ((1, 2, 3, 4), (5, 6, 7, 8)):
        for i in range(4):
            for j in range(i + 1, 4):
                rows.append(row(group[i], group[j], 2, 0, day))
                day += 1
    rows.append(row(1, 6, 1, 0, day))       # SF1
    rows.append(row(5, 2, 0, 1, day + 1))   # SF2
    rows.append(row(1, 2, 2, 1, day + 2))   # final
    return rows


def test_infer_knockout_flags_marks_the_bracket_only():
    rows = _edition(2018)
    flags = infer_knockout_flags(rows)
    assert len(flags) == len(rows) == 15
    assert flags[-3:] == [True, True, True]      # SFs + final
    assert not any(flags[:-3])                   # every group game stays False


def test_infer_knockout_flags_handles_pure_round_robin():
    # No bracket at all (everyone plays everyone once): nothing may be flagged.
    d = date(2018, 6, 1)
    rows = [{"home_id": h, "away_id": a, "pre_home": 1600.0, "pre_away": 1600.0,
             "is_neutral": True, "competition": "Copa América",
             "score_home": 1, "score_away": 1, "date": d + timedelta(days=i)}
            for i, (h, a) in enumerate([(1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3)])]
    assert infer_knockout_flags(rows) == [False] * 6


def test_wdl_and_grid_lam_scale_shrinks_expected_goals():
    """lam_scale multiplies BOTH lambdas: the grid must shift mass toward low
    scorelines (0-0 gains) while the identity scale reproduces the original."""
    base_wdl, base_grid = wdl_and_grid(1700.0, 1600.0, True, DEFAULT_PARAMS)
    same_wdl, same_grid = wdl_and_grid(1700.0, 1600.0, True, DEFAULT_PARAMS, lam_scale=1.0)
    assert same_wdl == base_wdl and same_grid == base_grid

    _, low_grid = wdl_and_grid(1700.0, 1600.0, True, DEFAULT_PARAMS, lam_scale=0.85)
    assert low_grid[0][0] > base_grid[0][0]


def test_ko_multiplier_gate_reports_per_multiplier_verdicts():
    rows = []
    for yr in range(2010, 2024, 2):
        rows.extend(_edition(yr))
    res = run_ko_multiplier_gate(rows, since_year=2010, n_boot=50)

    assert res["ko_matches"] > 0 and res["editions"] > 0
    assert set(res["multipliers"]) == {0.85, 0.90, 0.95}
    for m, cell in res["multipliers"].items():
        assert "d_exact_nll" in cell and len(cell["es_ci"]) == 2
        assert "d_log_loss" in cell and len(cell["ll_ci"]) == 2
        assert "d_top1" in cell and len(cell["t1_ci"]) == 2
        assert cell["verdict"] in ("SHIP", "do-not-ship")
        # Mechanical rule: SHIP iff exact-NLL CI upper < 0 AND log-loss holds.
        expect = cell["es_ci"][1] < 0 and cell["d_log_loss"] <= res["ll_tol"]
        assert (cell["verdict"] == "SHIP") == expect


def test_ko_multiplier_gate_empty_holdout_is_honest():
    res = run_ko_multiplier_gate([], since_year=2010, n_boot=10)
    assert res["ko_matches"] == 0
    assert all(cell["verdict"] == "do-not-ship" for cell in res["multipliers"].values())
