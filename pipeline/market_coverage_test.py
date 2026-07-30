"""Tests for the D0 closing-odds coverage census — hermetic, no network, no DB.

Acceptance criteria referenced here are from
docs/experiments/2026-07-29-d0-market-validation/PRE-REGISTRATION.md.
"""
from __future__ import annotations

import json
import textwrap
from datetime import date
from pathlib import Path

import pytest

from pipeline.club_data_manifest import (
    MANIFEST_PATH,
    expected_keys,
    pre_confirmation_keys,
)
from pipeline.ingest.football_data import ODDS_FAMILIES
from pipeline.market_coverage import (
    PROVIDER,
    ConfirmationFetchRefused,
    census_directory,
    census_file,
    compare_families,
    coverage_summary,
    fetch_captures,
    format_family_comparison,
    format_report,
    join_diagnostics,
    main,
)

_HEAD = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR"


def _csv(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return p


def _avgc_capture(tmp_path: Path, name: str = "E0_2324.csv") -> Path:
    return _csv(
        tmp_path,
        name,
        f"""
        {_HEAD},Time,AvgCH,AvgCD,AvgCA,PSCH,PSCD,PSCA,AvgH,AvgD,AvgA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,15:00,1.90,3.70,4.20,1.88,3.65,4.35,1.85,3.50,4.30
        E0,13/08/23,Everton,Fulham,0,1,A,14:00,2.40,3.30,3.10,2.42,3.28,3.05,2.35,3.25,3.15
        """,
    )


def _psc_only_capture(tmp_path: Path, name: str = "E0_1617.csv") -> Path:
    # The 2016-17..2018-19 shape: no AvgC*, but Pinnacle closing is present.
    return _csv(
        tmp_path,
        name,
        f"""
        {_HEAD},PSCH,PSCD,PSCA,AvgH,AvgD,AvgA
        E0,12/08/16,Arsenal,Chelsea,2,1,H,1.88,3.65,4.35,1.85,3.50,4.30
        E0,13/08/16,Everton,Fulham,0,1,A,2.42,3.28,3.05,2.35,3.25,3.15
        """,
    )


def _pre_closing_only_capture(tmp_path: Path, name: str = "E0_1516.csv") -> Path:
    return _csv(
        tmp_path,
        name,
        f"""
        {_HEAD},AvgH,AvgD,AvgA
        E0,12/08/15,Arsenal,Chelsea,2,1,H,1.85,3.50,4.30
        """,
    )


# ---------------------------------------------------------------- census (A1)


def test_census_reports_every_family_with_its_basis(tmp_path):
    c = census_file(_avgc_capture(tmp_path))
    by_key = {f.key: f for f in c.families}
    assert by_key["AvgC"].present and by_key["AvgC"].basis == "closing"
    assert by_key["PSC"].present and by_key["PSC"].bookmaker == "Pinnacle"
    assert by_key["Avg"].present and by_key["Avg"].basis == "pre_closing"
    assert not by_key["B365C"].present
    assert c.selected_closing == "AvgC"
    assert c.has_kickoff_time is True


def test_psc_only_capture_still_has_a_closing_line(tmp_path):
    # The finding this whole phase turns on: a file without AvgC* is NOT a file
    # without a closing line. Pinnacle closing is right there.
    c = census_file(_psc_only_capture(tmp_path))
    assert c.selected_closing == "PSC"
    assert c.has_closing is True
    assert c.abstains is False
    assert c.has_kickoff_time is False


def test_capture_with_no_closing_family_abstains(tmp_path):
    c = census_file(_pre_closing_only_capture(tmp_path))
    assert c.selected_closing is None
    assert c.abstains is True
    # It is not silently downgraded to the pre-closing family it does have.
    assert c.selected_any == "Avg"


def test_market_log_loss_is_computed_per_family(tmp_path):
    c = census_file(_avgc_capture(tmp_path))
    avgc = next(f for f in c.families if f.key == "AvgC")
    assert avgc.usable == 2
    assert avgc.market_log_loss is not None and avgc.market_log_loss > 0


# ------------------------------------------------------- denominators (A4)


def test_drop_reasons_are_exhaustive_and_sum_to_rows(tmp_path):
    p = _csv(
        tmp_path,
        "E0_2324.csv",
        f"""
        {_HEAD},AvgCH,AvgCD,AvgCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.90,3.70,4.20
        E0,not-a-date,Spurs,Wolves,1,1,D,1.90,3.70,4.20
        E0,13/08/23,Everton,Fulham,,1,A,2.40,3.30,3.10
        E0,14/08/23,Leeds,Burnley,1,0,,2.40,3.30,3.10
        E0,15/08/23,Villa,Brentford,1,0,H,,,
        E0,16/08/23,Brighton,Palace,1,0,H,1.00,3.30,3.10
        """,
    )
    c = census_file(p)
    assert c.rows == 6
    assert c.drops == {
        "unparseable_date": 1,
        "missing_or_invalid_score": 1,
        "missing_result": 1,
        "missing_odds": 1,
        "odds_not_above_one": 1,
    }
    priced = next(f.usable for f in c.families if f.key == "AvgC")
    # Exhaustive: every row is either priced or attributed to exactly one reason.
    assert priced + sum(c.drops.values()) == c.rows


def test_summary_shows_evidence_discarded_by_pinning_avgc(tmp_path):
    _avgc_capture(tmp_path, "E0_2324.csv")
    _psc_only_capture(tmp_path, "E0_1617.csv")
    census = census_directory(
        tmp_path, keys=["E0_2324", "E0_1617"], check_manifest=False
    )
    d = coverage_summary(census)["per_division"]["E0"]
    assert d["rows"] == 4
    assert d["closing_any_usable"] == 4  # both captures priceable
    assert d["closing_avgc_usable"] == 2  # only the AvgC-era one
    assert d["discarded_by_pinning_avgc"] == 2
    assert d["coverage_rate_closing_any"] == 1.0
    assert d["families_used"] == {"AvgC": 1, "PSC": 1}


def test_abstained_files_are_named_not_pooled(tmp_path):
    _avgc_capture(tmp_path, "E0_2324.csv")
    _pre_closing_only_capture(tmp_path, "E0_1516.csv")
    census = census_directory(
        tmp_path, keys=["E0_2324", "E0_1516"], check_manifest=False
    )
    summary = coverage_summary(census)
    d = summary["per_division"]["E0"]
    assert d["abstained_files"] == ["E0_1516"]
    # The abstained capture's rows stay in the denominator — hiding them would
    # turn an abstention into a silently better coverage rate.
    assert d["rows"] == 3
    assert d["closing_any_usable"] == 2
    assert "E0_1516" in format_report(census, summary)


# ------------------------------------------------------------ drift (§6)


def test_manifest_drift_is_recorded_and_manifest_is_not_rewritten(tmp_path):
    before = MANIFEST_PATH.read_bytes()
    # A real manifest key whose bytes deliberately do not match.
    _avgc_capture(tmp_path, "E0_2324.csv")
    census = census_directory(tmp_path, keys=["E0_2324"])
    assert [d["file"] for d in census.manifest_drift] == ["E0_2324"]
    drift = census.manifest_drift[0]
    assert drift["expected_sha256"] != drift["actual_sha256"]
    assert "DRIFT" in format_report(census, coverage_summary(census)).upper()
    # Re-pinning on drift would destroy the evidence that it drifted.
    assert MANIFEST_PATH.read_bytes() == before


def test_missing_captures_are_reported_not_skipped_silently(tmp_path):
    census = census_directory(tmp_path, keys=["E0_2324"], check_manifest=False)
    assert census.missing == ("E0_2324",)
    assert "MISSING" in format_report(census, coverage_summary(census))


# ------------------------------------------------- leakage audit L2 / L4


def test_join_is_exact_and_a_near_miss_does_not_match():
    """L2. Adjacent-date same-clubs must MISS, not be absorbed."""
    odds = [(date(2023, 8, 12), "Arsenal", "Chelsea")]
    model = [
        (date(2023, 8, 12), "Arsenal", "Chelsea"),  # exact
        (date(2023, 8, 13), "Arsenal", "Chelsea"),  # near miss: next day
    ]
    diag = join_diagnostics(model, odds)
    assert diag["n_eligible"] == 2
    assert diag["n_matched"] == 1
    assert diag["drops"]["fixture_absent"] == 1
    assert diag["coverage_rate"] == 0.5


def test_join_allows_the_existing_orientation_swap_and_says_so():
    odds = [(date(2023, 8, 12), "Chelsea", "Arsenal")]
    diag = join_diagnostics([(date(2023, 8, 12), "Arsenal", "Chelsea")], odds)
    assert diag["n_matched"] == 1
    assert diag["n_matched_orientation_swapped"] == 1


def test_join_separates_absent_fixture_from_absent_pairing():
    odds = [(date(2023, 8, 12), "Arsenal", "Spurs")]
    model = [
        (date(2023, 8, 12), "Arsenal", "Chelsea"),  # Arsenal played, pairing differs
        (date(2024, 1, 1), "Leeds", "Burnley"),  # nobody played
    ]
    diag = join_diagnostics(model, odds)
    assert diag["drops"] == {"same_day_pairing_absent": 1, "fixture_absent": 1}


def test_default_scope_never_opens_a_confirmation_capture(tmp_path):
    """L4. Poison the three *_2526 captures so any read_bytes() raises."""
    for key in pre_confirmation_keys()[:2]:
        _avgc_capture(tmp_path, f"{key}.csv")
    poisoned = [k for k in expected_keys() if k.endswith("_2526")]
    assert len(poisoned) == 3
    for key in poisoned:
        (tmp_path / f"{key}.csv").mkdir()

    census = census_directory(tmp_path, check_manifest=False)  # default scope
    assert census.scope == "pre_confirmation_27"
    assert len(census.files) == 2
    assert all(not k.endswith("_2526") for k in census.keys)

    # And prove the poison is real: the wider scope must actually raise.
    with pytest.raises(IsADirectoryError):
        census_directory(tmp_path, keys=expected_keys(), check_manifest=False)


# ----------------------------------------------------- provenance (A3/A6)


def test_provenance_travels_on_the_census():
    census = census_directory(Path("/nonexistent"), keys=["E0_2324"], check_manifest=False)
    assert census.provider is PROVIDER
    assert census.provider["provider"] == "football-data.co.uk"
    # Redistribution is not granted, and the record has to say so out loud.
    assert "NOT GRANTED" in census.provider["redistribution"]
    assert "no per-price timestamp" in census.provider["timestamp_semantics"]
    assert json.dumps(census.provider)  # serializable for the emitted artifact


# ------------------------------------------- holdout safety on FETCH (L4)


def test_fetch_refuses_confirmation_captures_by_default(tmp_path, monkeypatch):
    """Reading the burnt holdout and DOWNLOADING it are different decisions.

    `--include-confirmation` widens what is read. It must not also put the
    consumed 2025-26 season on disk, where the next careless glob finds it.
    """
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not fetch")
    )
    with pytest.raises(ConfirmationFetchRefused) as exc:
        fetch_captures(tmp_path, keys=expected_keys())
    assert "E0_2526" in str(exc.value)
    assert list(tmp_path.iterdir()) == []


def test_fetch_of_pre_confirmation_scope_is_not_blocked(tmp_path, monkeypatch):
    # The refusal must be specific to the holdout, not a blanket block.
    import urllib.request

    calls: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"Div,Date\n"

    def _fake(req, timeout=0):
        calls.append(req.full_url)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    written = fetch_captures(tmp_path, keys=["E0_2324"], delay_s=0)
    assert written == ["E0_2324"]
    assert calls == ["https://www.football-data.co.uk/mmz4281/2324/E0.csv"]


def test_scope_label_is_derived_from_the_keys_not_from_how_they_were_passed(tmp_path):
    # The CLI always passes an explicit list, so labelling by argument shape
    # stamped every artifact "explicit" — including one that read the holdout.
    _avgc_capture(tmp_path, "E0_2324.csv")
    assert (
        census_directory(tmp_path, keys=pre_confirmation_keys(), check_manifest=False).scope
        == "pre_confirmation_27"
    )
    assert (
        census_directory(tmp_path, keys=expected_keys(), check_manifest=False).scope
        == "includes_confirmation"
    )
    assert (
        census_directory(tmp_path, keys=["E0_2324"], check_manifest=False).scope
        == "partial_pre_confirmation"
    )


def test_cli_exits_non_zero_on_drift(tmp_path, capsys):
    # pipeline.club_data_manifest already exits 1 on drift. Two tools
    # disagreeing about whether 27/27 drift is an error is worse than either.
    _avgc_capture(tmp_path, "E0_2324.csv")
    assert main(["--dir", str(tmp_path)]) == 1
    assert "MANIFEST DRIFT" in capsys.readouterr().out


def test_drift_message_does_not_assert_a_cause_it_cannot_know(tmp_path):
    # The only input to this branch is a sha256 mismatch. A local edit, a
    # truncated download and a publisher revision are indistinguishable to it.
    _avgc_capture(tmp_path, "E0_2324.csv")
    census = census_directory(tmp_path, keys=["E0_2324"])
    text = format_report(census, coverage_summary(census))
    assert "not the recorded capture" in text
    assert "Cause is NOT established here" in text


# --------------------------------------------------- family comparison


def test_compare_families_pairs_only_captures_carrying_both(tmp_path):
    _avgc_capture(tmp_path, "E0_2324.csv")  # AvgC + PSC
    _psc_only_capture(tmp_path, "E0_1617.csv")  # PSC only
    census = census_directory(
        tmp_path, keys=["E0_2324", "E0_1617"], check_manifest=False
    )
    cmp = compare_families(census, "AvgC", "PSC")
    assert [p["key"] for p in cmp["paired"]] == ["E0_2324"]
    assert [o["key"] for o in cmp["only_PSC"]] == ["E0_1617"]
    assert cmp["discarded_by_pinning_AvgC"] == 2
    assert "E0_1617" in format_family_comparison(cmp)


def test_family_table_only_lists_families_the_publisher_documents_as_closing():
    """`VC` ends in C and is BetVictor PRE-closing; `VCC` is its closing twin.

    A "prefix ends in C" heuristic would label a pre-closing series closing in
    24 of the 27 captures. The table is an explicit allowlist for that reason,
    and the two families must never both be treated as closing.
    """
    keys = {f.key for f in ODDS_FAMILIES}
    assert "VC" not in keys  # would be a false positive under a naive rule
    for fam in ODDS_FAMILIES:
        if fam.basis == "closing":
            assert fam.key.endswith("C"), fam
        else:
            assert not fam.key.endswith("C"), fam


def test_confirmation_suffix_tracks_the_shared_holdout_constant():
    """The comment used to claim a test pinned these equal. None existed.

    Now the suffix is derived, and this pins it — so when the holdout rolls,
    the census scope rolls with it instead of guarding a stale season.
    """
    from pipeline.club_data_manifest import CONFIRM_SEASON
    from pipeline.market_coverage import _CONFIRMATION_SUFFIX

    assert _CONFIRMATION_SUFFIX == f"_{CONFIRM_SEASON}"
    assert all(k.endswith(_CONFIRMATION_SUFFIX) for k in expected_keys()
               if k not in pre_confirmation_keys())


def test_the_capture_fetcher_identifies_itself_honestly(tmp_path, monkeypatch):
    """Asserts the header actually SENT, not the source text.

    The provider whose licence this phase is careful about deserves a real
    agent string rather than a forged `curl/8`. Checking the source would also
    trip on the comment that explains why.
    """
    import urllib.request

    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"Div,Date\n"

    def _capture(req, timeout=0):
        seen["ua"] = req.get_header("User-agent")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _capture)
    fetch_captures(tmp_path, keys=["E0_2324"], delay_s=0)
    assert seen["ua"].startswith("finalwhistle-research/")
    assert "curl" not in seen["ua"]


def test_census_makes_no_network_call(tmp_path, monkeypatch):
    """A6. The census path is offline; fetching is a separate operator action."""
    import urllib.request

    def _boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("census must not open a URL")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    _avgc_capture(tmp_path, "E0_2324.csv")
    census = census_directory(tmp_path, keys=["E0_2324"], check_manifest=False)
    assert len(census.files) == 1
