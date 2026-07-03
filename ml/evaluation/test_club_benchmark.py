"""Offline tests for the club-football benchmark orchestrator.

No network, no DB. Everything runs off the committed fixture CSV
(ml/evaluation/fixtures/club_sample_epl.csv). Proves the Phase-1 pipeline
(docs/ROADMAP-ENGINE.md) reuses the Phase-0 engine end-to-end.
"""
from __future__ import annotations

import json
import math
import os

from ml.evaluation.market_benchmark import MatchedMatch
from pipeline.run_club_benchmark import build_club_matched, run_club_benchmark

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "club_sample_epl.csv"
)


def _is_prob_triple(p) -> bool:
    return (
        len(p) == 3
        and all(0.0 <= x <= 1.0 for x in p)
        and math.isclose(sum(p), 1.0, abs_tol=1e-9)
    )


def test_build_club_matched_returns_valid_matches():
    matched = build_club_matched([_FIXTURE], league="EPL 2023-24")
    assert len(matched) >= 8
    assert all(isinstance(m, MatchedMatch) for m in matched)
    for m in matched:
        assert _is_prob_triple(m.model_probs)
        assert _is_prob_triple(m.market_probs)
        assert m.label in ("H", "D", "A")
        assert m.home and m.away


def test_build_club_matched_sorted_oldest_first():
    matched = build_club_matched([_FIXTURE], league="EPL 2023-24")
    dates = [m.date for m in matched]
    assert dates == sorted(dates)


def test_build_club_matched_labels_match_scores():
    # The fixture opens with Arsenal 2-1 Nott'm Forest (a home win) on the
    # earliest date, so the first matched row must be labelled "H".
    matched = build_club_matched([_FIXTURE], league="EPL 2023-24")
    first = matched[0]
    assert first.home == "Arsenal"
    assert first.label == "H"


def test_benchmark_has_expected_keys():
    from ml.evaluation.market_benchmark import benchmark

    matched = build_club_matched([_FIXTURE], league="EPL 2023-24")
    result = benchmark(matched, n_bootstrap=200)
    for key in ("model", "market", "diff_log_loss", "diff_ci95"):
        assert key in result


def test_format_report_contains_verdict():
    from ml.evaluation.market_benchmark import benchmark, format_report

    matched = build_club_matched([_FIXTURE], league="EPL 2023-24")
    report = format_report(benchmark(matched, n_bootstrap=200), "EPL 2023-24")
    assert "verdict:" in report


def test_run_club_benchmark_writes_ready_json(tmp_path):
    out = tmp_path / "club_benchmark.json"
    rc = run_club_benchmark(
        [_FIXTURE], league="EPL 2023-24", emit_json=str(out)
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["dataset"] == "EPL 2023-24"
    assert payload["n_matches"] >= 8
    assert "verdict" in payload


def test_run_club_benchmark_empty_returns_1(tmp_path, caplog):
    # A header-only CSV yields no matched rows -> error exit, no crash.
    empty = tmp_path / "empty.csv"
    empty.write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA\n",
        encoding="utf-8",
    )
    rc = run_club_benchmark([str(empty)], league="EPL 2023-24")
    assert rc == 1
