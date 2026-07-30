"""Tests for the E1.1 runner (offline, hermetic).

Two negative properties matter most: no network, and never the consumed
2025-26 holdout. `pipeline/experiment_club_eval.py::load_matches` violates
both, which is why this runner exists instead of reusing it.

Also enforces Appendix A1's bargain: the `policy` seam added to FR-5's fitter
must be bit-identical for every existing caller, or E1 has changed something
that serves in order to measure something that does not.
"""
from __future__ import annotations

import urllib.request
from datetime import date
from pathlib import Path

import pytest

from ml.evaluation.club_tempo import CAP_SENSITIVITY, GRID
from pipeline.club_data_manifest import CONFIRM_SEASON, PRE_CONFIRMATION_SEASONS
from pipeline.run_e1_tempo import (
    BONFERRONI_K,
    BOOTSTRAP_SEED,
    CORRECTED_ALPHA,
    LEAGUES,
    MAX_SATURATED_FRAC,
    PRACTICAL_FLOOR,
    SCORED_SEASONS,
    _interval,
    format_report,
    load_matches,
    main,
    make_fitter,
    run_league,
    stop_conditions,
)

TEAMS = ["Arsenal", "Chelsea", "Spurs", "Everton", "Fulham", "Brentford"]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - only on failure
        raise AssertionError("E1 must never reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)


def _season_csv(season: str) -> str:
    head = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR"
    yy = 2000 + int(season[:2])
    rows, n = [], 0
    for i, h in enumerate(TEAMS):
        for j, a in enumerate(TEAMS):
            if i == j:
                continue
            n += 1
            gh, ga = (2, 1) if n % 2 else (1, 1)
            rows.append(f"E0,{(n % 27) + 1:02d}/{(n % 9) + 1:02d}/{yy},{h},{a},"
                        f"{gh},{ga},{'H' if gh > ga else 'D'}")
    return head + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def csv_dir(tmp_path) -> Path:
    d = tmp_path / "club"
    d.mkdir()
    for s in PRE_CONFIRMATION_SEASONS:
        (d / f"E0_{s}.csv").write_text(_season_csv(s))
    return d


# --- Appendix A1: the seam must not change anything that serves ----------

def test_fit_offsets_without_policy_is_unchanged_by_the_seam():
    """The bargain A1 struck: additive, default-preserving. If this drifts, E1
    has altered the FR-5 path in order to measure something that is not it."""
    from ml.models.team_offsets import shrink_and_cap
    from pipeline.fit_attack_defence import fit_offsets

    rows = [
        {"date": date(2020, 1, i + 1), "home_id": "A" if i % 2 else "B",
         "away_id": "B" if i % 2 else "A", "pre_home": 1500.0 + i,
         "pre_away": 1490.0, "is_neutral": False,
         "score_home": i % 3, "score_away": (i + 1) % 3}
        for i in range(20)
    ]
    ref = date(2021, 1, 1)
    default = fit_offsets(rows, ref)
    explicit = fit_offsets(rows, ref, policy=shrink_and_cap)
    assert default == explicit
    assert default, "fixture produced no offsets; the test would assert nothing"


def test_the_parameterised_policy_is_exactly_the_shipped_one_at_defaults():
    from ml.models.team_offsets import (
        FULL_WEIGHT_EFF_MATCHES,
        OFFSET_CAP,
        policy_with,
        shrink_and_cap,
    )
    p = policy_with()
    for atk in (-0.5, -0.075, -0.01, 0.0, 0.01, 0.075, 0.5):
        for dfn in (-0.3, 0.0, 0.3):
            for n in (0.0, 0.5, 5.0, 29.9, 30.0, 100.0):
                assert p(atk, dfn, n) == shrink_and_cap(atk, dfn, n)
    assert OFFSET_CAP == 0.075
    assert FULL_WEIGHT_EFF_MATCHES == 30.0


def test_the_policy_actually_varies_when_asked_to():
    """Otherwise the grid is nine copies of one point."""
    from ml.models.team_offsets import policy_with
    tight, loose = policy_with(cap=0.05), policy_with(cap=0.15)
    assert tight(0.5, 0.0, 100.0)[0] == pytest.approx(0.05)
    assert loose(0.5, 0.0, 100.0)[0] == pytest.approx(0.15)
    slow, fast = policy_with(full_weight_eff=60.0), policy_with(full_weight_eff=10.0)
    assert slow(0.075, 0.0, 10.0)[0] < fast(0.075, 0.0, 10.0)[0]


# --- the quarantine and the network --------------------------------------

def test_the_confirmation_season_is_never_read(csv_dir):
    assert not (csv_dir / f"E0_{CONFIRM_SEASON}.csv").exists()
    ms = load_matches(csv_dir, "E0")
    assert ms and all(m.season != CONFIRM_SEASON for m in ms)


def test_a_missing_capture_raises_instead_of_downloading(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="never downloads"):
        load_matches(empty, "E0")


def test_the_confirmation_season_on_disk_is_still_not_read(csv_dir):
    (csv_dir / f"E0_{CONFIRM_SEASON}.csv").write_text(_season_csv(CONFIRM_SEASON))
    assert all(m.season != CONFIRM_SEASON for m in load_matches(csv_dir, "E0"))


def test_scored_seasons_exclude_the_burn_in_and_the_holdout():
    assert set(SCORED_SEASONS) == set(PRE_CONFIRMATION_SEASONS) - {"1617", "1718"}
    assert CONFIRM_SEASON not in SCORED_SEASONS


# --- the fitter cannot see the season it is fitting for -------------------

def test_the_fitter_uses_only_matches_strictly_before_the_cutoff(csv_dir):
    from ml.evaluation.club_walkforward import EloConfig, replay
    from ml.models.params import load_params

    ms = load_matches(csv_dir, "E0")
    pre = replay(ms, EloConfig(), "Premier League")
    fit, rows = make_fitter(ms, pre, load_params(), 60.0)
    cutoff = min(m.date for m in ms if m.season == "1819")

    fitted = fit(cutoff, GRID[0])
    # Every club in the fit must have played before the cutoff.
    played_before = {m.home for m in ms if m.date < cutoff} | \
                    {m.away for m in ms if m.date < cutoff}
    assert set(fitted) <= played_before
    assert fitted, "no offsets fitted; the assertion above would be vacuous"


def test_a_cutoff_before_all_data_yields_no_offsets(csv_dir):
    from ml.evaluation.club_walkforward import EloConfig, replay
    from ml.models.params import load_params

    ms = load_matches(csv_dir, "E0")
    pre = replay(ms, EloConfig(), "Premier League")
    fit, _ = make_fitter(ms, pre, load_params(), 60.0)
    assert fit("1900-01-01", GRID[0]) == {}


# --- the §7 verdict rule --------------------------------------------------

def test_an_effect_inside_its_own_half_width_prints_unresolved():
    """The rule D0-B broke. A tiny mean with a wide interval is not a direction."""
    deltas = {
        f"s{i}": [0.001 * (i - 2), -0.02 * (i % 3), 0.03 * ((i + 1) % 4), -0.01]
        for i in range(8)
    }
    out = _interval(deltas, 400, CORRECTED_ALPHA)
    assert out["half_width"] > 0
    assert out["verdict"] == "UNRESOLVED at this sample size"
    assert not out["excludes_zero"]


def test_identical_clusters_are_degenerate_not_certain():
    """Every resample draws the same values, so the bootstrap measures nothing
    and returns a zero-width interval. Reporting that as credible is the failure
    `season_clustered_ci`'s docstring already warns about."""
    deltas = {f"s{i}": [0.001, -0.002, 0.003, -0.001] for i in range(6)}
    out = _interval(deltas, 200, CORRECTED_ALPHA)
    assert out["half_width"] == 0.0
    assert out["verdict"].startswith("DEGENERATE")
    assert not out["excludes_zero"]


def test_a_large_consistent_effect_is_reported_as_credible():
    # Varied across clusters, so the bootstrap has something to resample, but
    # every cluster points the same way.
    deltas = {f"s{i}": [-0.5 - 0.02 * i, -0.4 - 0.01 * i, -0.6] for i in range(8)}
    out = _interval(deltas, 400, CORRECTED_ALPHA)
    assert out["verdict"] == "CANDIDATE BETTER (credible)"
    assert out["excludes_zero"]


def test_intervals_are_bonferroni_corrected_not_ninety_five_percent():
    assert BONFERRONI_K == 3
    assert CORRECTED_ALPHA == pytest.approx(0.05 / 3)
    deltas = {f"s{i}": [0.01 * ((-1) ** j) for j in range(30)] for i in range(6)}
    wide = _interval(deltas, 400, CORRECTED_ALPHA)
    narrow = _interval(deltas, 400, 0.05)
    assert wide["half_width"] >= narrow["half_width"]


def test_the_seed_is_the_pre_registered_one():
    assert BOOTSTRAP_SEED == 26


# --- stop conditions ------------------------------------------------------

def _res(league, mean, excludes, guard_mean=0.0, guard_excludes=False, sat=0.0):
    return {
        "league": league,
        "primary": {"mean": mean, "excludes_zero": excludes},
        "guardrail_1x2": {"mean": guard_mean, "excludes_zero": guard_excludes},
        "diagnostics": {"saturated_frac": sat},
    }


def test_s1_fires_when_nothing_resolves_anywhere():
    fired = stop_conditions([_res("a", -0.001, False), _res("b", 0.0, False),
                             _res("c", -0.002, False)])
    assert any(f.startswith("S1") for f in fired)


def test_s1_does_not_fire_when_something_resolves():
    fired = stop_conditions([_res("a", -0.02, True), _res("b", 0.0, False),
                             _res("c", -0.002, False)])
    assert not any(f.startswith("S1") for f in fired)


def test_s1_says_so_when_the_run_was_partial():
    """A one-league run must not print the phase's three-league determination."""
    fired = stop_conditions([_res("a", -0.001, False)])
    assert any("PARTIAL RUN" in f for f in fired)


def test_s2_fires_when_every_credible_gain_is_below_the_practical_floor():
    fired = stop_conditions([_res("a", -0.001, True), _res("b", -0.002, True),
                             _res("c", 0.0, False)])
    assert any(f.startswith("S2") for f in fired)


def test_s2_does_not_fire_on_a_gain_above_the_floor():
    fired = stop_conditions([_res("a", -0.02, True), _res("b", 0.0, False),
                             _res("c", 0.0, False)])
    assert not any(f.startswith("S2") for f in fired)


def test_s3_fires_only_when_the_guardrail_is_credibly_WORSE():
    worse = stop_conditions([_res("a", -0.02, True, guard_mean=+0.01,
                                  guard_excludes=True)])
    assert any(f.startswith("S3") for f in worse)
    better = stop_conditions([_res("a", -0.02, True, guard_mean=-0.01,
                                   guard_excludes=True)])
    assert not any(f.startswith("S3") for f in better)


def test_s4_fires_above_the_saturation_ceiling():
    fired = stop_conditions([_res("a", -0.02, True, sat=MAX_SATURATED_FRAC + 0.01)])
    assert any(f.startswith("S4") for f in fired)
    ok = stop_conditions([_res("a", -0.02, True, sat=MAX_SATURATED_FRAC - 0.01)])
    assert not any(f.startswith("S4") for f in ok)


# --- end to end -----------------------------------------------------------

def test_run_league_produces_a_complete_result(csv_dir):
    r = run_league("epl", csv_dir, n_bootstrap=60)
    assert r["league"] == "epl"
    assert r["n_scored"] > 0
    for key in ("primary", "guardrail_1x2"):
        assert {"mean", "ci", "verdict", "paired_sd"} <= set(r[key])
    assert set(r["cap_sensitivity"]) == {p.label() for p in CAP_SENSITIVITY}
    assert set(r["chosen"]) == set(SCORED_SEASONS)


def test_the_report_states_the_verdict_and_the_stop_conditions(csv_dir):
    r = run_league("epl", csv_dir, n_bootstrap=60)
    text = format_report([r], stop_conditions([r]))
    assert "SELECTS ONLY" in text
    assert "practical floor" in text
    assert "STOP CONDITIONS" in text
    assert "cap-saturated" in text


def test_n_bootstrap_below_one_is_rejected(csv_dir):
    with pytest.raises(SystemExit):
        main(["--csv-dir", str(csv_dir), "--league", "epl", "--n-bootstrap", "0"])


# --- §11: this phase promotes nothing -------------------------------------

def test_no_served_parameter_or_artifact_is_changed_by_this_phase():
    """§11, enforced against git rather than trust. Appendix A1 permits exactly
    two additive edits; anything touching a served VALUE must still fail."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"],
                          cwd=root, capture_output=True, text=True)
    if base.returncode != 0:  # pragma: no cover
        pytest.skip("no origin/main to compare against")
    merge_base = base.stdout.strip()

    for guarded in ("pipeline/leagues.py", "ml/models/model_params.json"):
        diff = subprocess.run(["git", "diff", "--exit-code", merge_base, "--", guarded],
                              cwd=root, capture_output=True, text=True)
        assert diff.returncode == 0, f"{guarded} differs:\n{diff.stdout}"

    # team_offsets.py may gain policy_with (A1) but no constant may move, and
    # no existing function body may change.
    src = (root / "ml" / "models" / "team_offsets.py").read_text()
    assert "OFFSET_CAP = 0.075" in src
    assert "FULL_WEIGHT_EFF_MATCHES = 30.0" in src


def test_team_offsets_stays_disabled_in_the_served_params():
    import json
    root = Path(__file__).resolve().parent.parent
    params = json.loads((root / "ml" / "models" / "model_params.json").read_text())
    assert params["team_offsets"] is None
