"""Tests for the D0-B totals benchmark runner (offline, hermetic).

The two properties that matter most here are negative ones: this runner must
never reach the network, and must never open the consumed 2025-26 holdout.
`pipeline/experiment_club_eval.py::load_matches` does both — it iterates
SEASON_CODES including "2526" and downloads whatever is not cached — which is
precisely why this runner exists instead of reusing it.
"""
from __future__ import annotations

import textwrap
import urllib.request
from pathlib import Path

import pytest

from pipeline.club_data_manifest import CONFIRM_SEASON, PRE_CONFIRMATION_SEASONS
from pipeline.run_club_totals_benchmark import (
    FIT_SEASONS,
    LEAGUES,
    SCORED_SEASONS,
    format_report,
    load_division_matches,
    load_division_totals,
    run_league,
)

TEAMS = ["Arsenal", "Chelsea", "Spurs", "Everton"]
_CLOSING = "AvgC>2.5,AvgC<2.5"
_BETBRAIN = "BbAv>2.5,BbAv<2.5"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any fetch at all fails the test that caused it."""
    def _boom(*a, **k):  # pragma: no cover - only runs on failure
        raise AssertionError("this runner must never reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)


def _season_csv(season: str, *, closing: bool) -> str:
    """A tiny round-robin. Alternating scorelines give both labels."""
    cols = _CLOSING if closing else _BETBRAIN
    head = f"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,{cols}"
    yy = 2000 + int(season[:2])
    rows = []
    n = 0
    for i, h in enumerate(TEAMS):
        for j, a in enumerate(TEAMS):
            if i == j:
                continue
            n += 1
            gh, ga = (2, 1) if n % 2 else (1, 1)  # 3 goals then 2 goals
            day = (n % 28) + 1
            month = (n % 9) + 1
            rows.append(
                f"E0,{day:02d}/{month:02d}/{yy},{h},{a},{gh},{ga},"
                f"{'H' if gh > ga else 'D'},1.90,1.95"
            )
    return head + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def csv_dir(tmp_path) -> Path:
    """Nine pre-confirmation captures; the oldest three carry Betbrain only.

    Mirrors the real corpus shape: a closing 1X2 line everywhere, a closing
    TOTALS line only from 2019-20.
    """
    d = tmp_path / "club"
    d.mkdir()
    for season in PRE_CONFIRMATION_SEASONS:
        closing = season not in ("1617", "1718", "1819")
        (d / f"E0_{season}.csv").write_text(_season_csv(season, closing=closing))
    return d


# --- the quarantine -------------------------------------------------------

def test_confirmation_season_is_never_read(csv_dir):
    # The file does not exist; a loader with a network fallback would fetch it.
    assert not (csv_dir / f"E0_{CONFIRM_SEASON}.csv").exists()
    ms = load_division_matches(csv_dir, "E0")
    assert ms and all(m.season != CONFIRM_SEASON for m in ms)
    assert set(m.season for m in ms) == set(PRE_CONFIRMATION_SEASONS)


def test_a_missing_capture_raises_instead_of_downloading(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="never downloads"):
        load_division_matches(empty, "E0")


def test_confirmation_season_present_on_disk_is_still_not_scored(csv_dir):
    """Even if someone drops the holdout into the directory, it is not read."""
    (csv_dir / f"E0_{CONFIRM_SEASON}.csv").write_text(
        _season_csv(CONFIRM_SEASON, closing=True)
    )
    ms = load_division_matches(csv_dir, "E0")
    assert all(m.season != CONFIRM_SEASON for m in ms)
    totals, census = load_division_totals(csv_dir, "E0")
    assert all(r["season"] != CONFIRM_SEASON for r in totals)
    assert all(CONFIRM_SEASON not in c["file"] for c in census)


# --- coverage and abstention ---------------------------------------------

def test_files_without_a_closing_totals_family_abstain_and_are_named(csv_dir):
    _totals, census = load_division_totals(csv_dir, "E0")
    abstained = [c for c in census if c["family"] is None]
    assert {c["file"] for c in abstained} == {
        "E0_1617.csv", "E0_1718.csv", "E0_1819.csv"
    }
    assert all(c["reason"] == "no_closing_totals_columns" for c in abstained)
    # The denominator stays visible: an abstained file reports its row count.
    assert all(c["rows"] > 0 and c["usable"] == 0 for c in abstained)


def test_census_covers_every_pre_confirmation_capture(csv_dir):
    _totals, census = load_division_totals(csv_dir, "E0")
    assert len(census) == len(PRE_CONFIRMATION_SEASONS)
    assert all(c["sha256"] for c in census)


def test_usable_plus_dropped_equals_rows_for_every_file(csv_dir):
    _totals, census = load_division_totals(csv_dir, "E0")
    for c in census:
        assert c["usable"] + c["dropped"] == c["rows"], c["file"]


def test_burn_in_seasons_are_replayed_but_never_scored(csv_dir):
    ms = load_division_matches(csv_dir, "E0")
    totals, _ = load_division_totals(csv_dir, "E0")
    assert any(m.season == "1617" for m in ms)          # replayed
    assert not any(r["season"] == "1617" for r in totals)  # not scored


# --- the split ------------------------------------------------------------

def test_fit_and_scored_seasons_are_disjoint_and_priced():
    assert not (set(FIT_SEASONS) & set(SCORED_SEASONS))
    priced = set(PRE_CONFIRMATION_SEASONS) - {"1617", "1718", "1819"}
    assert set(FIT_SEASONS) | set(SCORED_SEASONS) == priced
    assert CONFIRM_SEASON not in set(FIT_SEASONS) | set(SCORED_SEASONS)


# --- end to end -----------------------------------------------------------

def test_run_league_produces_a_complete_result(csv_dir):
    r = run_league("epl", csv_dir, n_bootstrap=50)
    assert r["league"] == "epl" and r["division"] == "E0"
    assert r["n_matches"] > 0 and r["n_unjoined"] == 0
    assert r["market_basis"] == "closing (AvgC)"
    for key in ("model", "control", "market", "constant"):
        assert set(r[key]) == {"log_loss", "brier", "accuracy"}
    assert r["intervals"]["iso_week"]["role"].startswith("PRIMARY")
    assert r["resolution"]["paired_sd"] >= 0
    assert r["params"]["served"]["base"] and r["params"]["control"]["base"]


def test_served_and_control_params_are_recorded_separately(csv_dir):
    r = run_league("bundesliga", csv_dir.parent / "club", n_bootstrap=50) \
        if False else run_league("epl", csv_dir, n_bootstrap=50)
    # EPL ships base 1.30 over a 1.20 global; the receipt must show both, or a
    # reader cannot tell which model produced the number.
    assert r["params"]["served"]["base"] != r["params"]["control"]["base"]


def test_an_unjoined_priced_row_is_a_hard_error_by_default(csv_dir, monkeypatch):
    import pipeline.run_club_totals_benchmark as mod

    real = mod.load_division_totals

    def _with_ghost(d, division):
        recs, census = real(d, division)
        recs.append({**recs[0], "home_team": "Nobody FC"})
        return recs, census

    monkeypatch.setattr(mod, "load_division_totals", _with_ghost)
    with pytest.raises(AssertionError, match="did not join"):
        run_league("epl", csv_dir, n_bootstrap=20)
    # ...and is downgradeable to a report for diagnosis only.
    r = run_league("epl", csv_dir, n_bootstrap=20, strict_join=False)
    assert r["n_unjoined"] == 1


def test_report_states_the_in_sample_caveat_and_every_denominator(csv_dir):
    text = format_report([run_league("epl", csv_dir, n_bootstrap=50)])
    assert "IN-SAMPLE" in text
    assert "SELECTS NOTHING" in text
    assert "information budget" in text
    assert "RESOLVED AT THIS SAMPLE SIZE" in text
    # Abstentions are named in the report, not merely absent from a total.
    assert "E0_1617.csv" in text


def test_every_registered_league_is_runnable_shape(csv_dir):
    # Only E0 fixtures exist here; the point is that the table is well formed.
    assert set(LEAGUES) == {"epl", "laliga", "bundesliga"}
    for _lg, (div, comp, adv) in LEAGUES.items():
        assert div and comp and adv > 0
