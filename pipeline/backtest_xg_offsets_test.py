"""Smoke test for the A/B/C WC backtest sanity report (Phase 7).

This is NOT the proof bar (see docs/superpowers/plans/2026-07-04-statsbomb-xg-
team-offsets.md, Phase 7): xG exists only in recent editions' training windows
(~2 clusters, too few to exclude zero either way). The report's job is to run
without raising and print honest per-edition xG coverage so a null result reads
as "underpowered here," not "xG doesn't help." Pure over synthetic rows — no
DB, no network.
"""
from __future__ import annotations

from datetime import date, timedelta

from pipeline.backtest_xg_offsets import run_abc_backtest


def _row(home_id, away_id, score_home, score_away, d, competition, xg_a=None, xg_b=None,
         pre_home=1500.0, pre_away=1500.0, is_neutral=True):
    return {
        "home_id": home_id,
        "away_id": away_id,
        "score_home": score_home,
        "score_away": score_away,
        "date": d,
        "competition": competition,
        "is_neutral": is_neutral,
        "pre_home": pre_home,
        "pre_away": pre_away,
        "xg_a": xg_a,
        "xg_b": xg_b,
    }


def _synthetic_history(edition_year: int, n_teams: int = 8) -> list[dict]:
    """Round-robin-ish history: a training tail of club/friendly matches (no xG
    coverage, so goals and xG fits are IDENTICAL -> kappa~=0 fixture) followed
    by a small held-out "World Cup" edition with a couple of xG-covered rows."""
    rows: list[dict] = []
    start = date(edition_year - 3, 1, 1)
    rid = 0
    for day_offset in range(0, 40):
        d = start + timedelta(days=day_offset * 10)
        h = rid % n_teams
        a = (rid + 1) % n_teams
        if h == a:
            a = (a + 1) % n_teams
        rows.append(_row(h, a, (rid % 3), (rid % 2), d, "Friendly"))
        rid += 1

    # Held-out WC edition: a handful of matches, two of them carrying xG.
    wc_start = date(edition_year, 6, 1)
    wc_rows = [
        _row(0, 1, 2, 1, wc_start, "FIFA World Cup", xg_a=1.8, xg_b=1.1),
        _row(2, 3, 1, 1, wc_start + timedelta(days=1), "FIFA World Cup", xg_a=0.9, xg_b=0.95),
        _row(4, 5, 0, 0, wc_start + timedelta(days=2), "FIFA World Cup"),
        _row(6, 7, 3, 0, wc_start + timedelta(days=3), "FIFA World Cup"),
    ]
    rows.extend(wc_rows)
    return rows


def test_abc_report_runs_and_prints_coverage(capsys):
    """On a tiny synthetic history the report produces A/B/C log-loss + per-
    edition coverage without raising, and C is never far from B on a kappa~=0
    fixture (no real xG signal upstream of the WC edition -> the xG fit and the
    goals fit train on the same data -> C should track B closely)."""
    rows = _synthetic_history(2022)

    report = run_abc_backtest(rows, editions=[2022])

    out = capsys.readouterr().out
    assert "2022" in out
    assert "coverage" in out.lower()

    assert report["editions"][0]["year"] == 2022
    edition = report["editions"][0]
    for key in ("a_no_offsets", "b_goals_offsets", "c_xg_offsets"):
        assert key in edition
        assert edition[key]["log_loss"] == edition[key]["log_loss"]  # not NaN

    # Sanity, not significance: C's log-loss must not be wildly different from
    # B's on a fixture where the xG signal barely diverges from goals.
    b_ll = edition["b_goals_offsets"]["log_loss"]
    c_ll = edition["c_xg_offsets"]["log_loss"]
    assert abs(c_ll - b_ll) < 0.5

    assert edition["xg_coverage"]["matches"] == 4
    assert edition["xg_coverage"]["xg_covered"] == 2


def test_abc_report_handles_no_xg_coverage_at_all():
    """An edition with zero xG-covered rows anywhere in history must still run
    (kill-switch: build_xg_offsets-style empty-S no-op), reporting coverage=0
    rather than raising."""
    rows = _synthetic_history(2018)
    rows = [dict(r, xg_a=None, xg_b=None) for r in rows]

    report = run_abc_backtest(rows, editions=[2018])
    edition = report["editions"][0]
    assert edition["xg_coverage"]["xg_covered"] == 0
    assert edition["c_xg_offsets"]["log_loss"] == edition["c_xg_offsets"]["log_loss"]
