"""The operator-facing report must show everything the operator must act on."""

from pipeline.entities.reconcile import MarketOutcome, ReconcileReport
from pipeline.run_market_resolution import _print_report


def _report():
    return ReconcileReport(
        dry_run=True,
        outcomes=[
            MarketOutcome(venue="kalshi", venue_key="KX-1", action="proposed",
                          status="proposed", reason="review hint"),
            MarketOutcome(venue="kalshi", venue_key="KX-2", action="unmapped",
                          status="unmapped", reason="no fixture"),
        ],
        data_gaps=[
            "match 7 is not a candidate: no internal entity for team:9",
            "match 3 is not a candidate: no internal entity for team:2, tournament:1",
        ],
    )


def test_data_gaps_are_printed_deterministically(capsys):
    """fixture_candidates fills data_gaps; a report that hides them leaves the
    operator staring at 'no fixture shares this pairing' with no way to know
    which link-entity rows are owed."""
    _print_report(_report())

    out = capsys.readouterr().out
    assert "data gaps (2):" in out
    assert "! match 3 is not a candidate: no internal entity for team:2, tournament:1" in out
    assert "! match 7 is not a candidate: no internal entity for team:9" in out
    assert out.index("match 3") < out.index("match 7"), "sorted, deterministic"
    assert "DRY RUN" in out
    assert '"proposed": 1' in out


def test_an_empty_gap_list_prints_no_gap_section(capsys):
    report = _report()
    report.data_gaps = []

    _print_report(report)

    assert "data gaps" not in capsys.readouterr().out
