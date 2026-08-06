"""Safety rails of the UCL fit runner (pipeline/experiment_ucl_eval.py)."""
import pytest

from ml.evaluation.club_walkforward import ClubMatch
from pipeline.experiment_ucl_eval import (
    CANDIDATES,
    SELECTION_SEASONS,
    UCL_CONFIRM_SEASON,
    UCL_FINAL_CONFIG,
    _weekly,
    run_selection,
)


def _m(season, day, home="A", away="B", gh=1, ga=0):
    return ClubMatch(season=season, home=home, away=away,
                     goals_home=gh, goals_away=ga, date=day)


def test_selection_never_scores_the_quarantined_edition():
    assert UCL_CONFIRM_SEASON not in SELECTION_SEASONS


def test_frozen_config_is_the_recorded_ship_list():
    """The confirmation consumed the 2025 edition against exactly this dict
    (evidence card 2026-08-06). Changing it without a new selection phase and
    a fresh holdout is multiple testing against a burnt edition."""
    assert UCL_FINAL_CONFIG == {"base": 1.44}


def test_weekly_reclusters_deltas_by_iso_week():
    matches = [
        _m("2023", "2023-09-19"), _m("2023", "2023-09-20", home="C", away="D"),
        _m("2023", "2023-10-03", home="E", away="F"),
    ]
    weekly = _weekly({"2023": [0.1, 0.2, 0.3]}, matches)
    assert weekly == {"2023-W38": [0.1, 0.2], "2023-W40": [0.3]}


def test_selection_runs_on_synthetic_editions_and_reports_weekly_clusters():
    # Two tiny editions before each scored one so walk-forward always has a
    # prior to fit on; deterministic scores keep the run instant.
    matches = []
    for i, season in enumerate(["2022", "2023", "2024"]):
        for wk in range(1, 5):
            matches.append(_m(season, f"{2022 + i}-10-{wk + 3:02d}",
                              home=f"H{wk}", away=f"A{wk}", gh=2, ga=1))
    r = run_selection("U1_base", matches, n_bootstrap=50)
    assert r["mode"] == "selection"
    assert r["cluster"] == "matchweek"
    assert set(r["chosen_per_season"]) == {"2023", "2024"}
    assert r["n_matches"] == 8  # 2023 + 2024 scored; 2022 only opens the replay


def test_candidate_grids_match_the_preregistered_domestic_tracks():
    bases = [p[0] for p in CANDIDATES["U1_base"][0]]
    advs = [p[0] for p in CANDIDATES["U2_home_adv"][0]]
    assert bases[0] == 1.10 and bases[-1] == 1.80  # T1.1's grid
    assert advs[0] == 20.0 and advs[-1] == 120.0   # T1.5's grid


def test_confirmation_refuses_without_a_frozen_config(monkeypatch):
    import pipeline.experiment_ucl_eval as mod

    monkeypatch.setattr(mod, "UCL_FINAL_CONFIG", None)
    with pytest.raises(SystemExit):
        mod.run_confirmation([_m("2025", "2025-09-16")], n_bootstrap=10)
