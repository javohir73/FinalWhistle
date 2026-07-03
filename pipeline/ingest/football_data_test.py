"""Tests for the football-data.co.uk club-CSV parser (offline, no network).

The parser feeds the club-football benchmark (docs/ROADMAP-ENGINE.md, Phase 1).
It must prefer the CLOSING-odds columns and skip malformed rows without dying.
"""
from __future__ import annotations

import textwrap

import pytest

from pipeline.ingest.football_data import load_football_data_csv


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return str(p)


def test_prefers_avg_closing_over_bet365(tmp_path):
    # Both AvgC* (market-average closing) and B365* (Bet365, non-closing) present.
    # The parser must choose AvgC* and record it as the source.
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,AvgCH,AvgCD,AvgCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.80,3.60,4.50,1.90,3.70,4.20
        """,
    )
    records = load_football_data_csv(csv)
    assert len(records) == 1
    r = records[0]
    assert r["odds_source"] == "AvgC"
    # AvgC* values, not B365* values.
    assert r["odds_home"] == 1.90
    assert r["odds_draw"] == 3.70
    assert r["odds_away"] == 4.20


def test_falls_back_when_no_closing_columns(tmp_path):
    # Only non-closing AvgH/AvgD/AvgA present -> use them.
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.85,3.50,4.30
        """,
    )
    records = load_football_data_csv(csv)
    assert len(records) == 1
    assert records[0]["odds_source"] == "Avg"
    assert records[0]["odds_home"] == 1.85


def test_parses_ddmmyy_dates(tmp_path):
    from datetime import date

    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.90,3.70,4.20
        E0,26/12/2023,Liverpool,Burnley,1,0,H,1.30,5.00,9.00
        """,
    )
    records = load_football_data_csv(csv)
    assert records[0]["date"] == date(2023, 8, 12)  # DD/MM/YY
    assert records[1]["date"] == date(2023, 12, 26)  # DD/MM/YYYY


def test_skips_rows_with_missing_scores(tmp_path):
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.90,3.70,4.20
        E0,13/08/23,Man City,Newcastle,,,,1.40,4.80,7.50
        """,
    )
    records = load_football_data_csv(csv)
    assert len(records) == 1
    assert records[0]["home_team"] == "Arsenal"


def test_skips_rows_with_non_numeric_or_bad_odds(tmp_path):
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.90,3.70,4.20
        E0,13/08/23,Man City,Spurs,3,1,H,x,3.70,4.20
        E0,14/08/23,Liverpool,Spurs,1,1,D,1.00,3.70,4.20
        """,
    )
    records = load_football_data_csv(csv)
    # Row 2 (non-numeric odds) and row 3 (odds == 1.0, not > 1.0) are dropped.
    assert len(records) == 1
    assert records[0]["home_team"] == "Arsenal"


def test_all_returned_odds_greater_than_one(tmp_path):
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.90,3.70,4.20
        E0,13/08/23,Man City,Newcastle,3,0,H,1.40,4.80,7.50
        """,
    )
    records = load_football_data_csv(csv)
    assert records
    for r in records:
        assert r["odds_home"] > 1.0
        assert r["odds_draw"] > 1.0
        assert r["odds_away"] > 1.0


def test_prefers_psc_over_b365c(tmp_path):
    # No AvgC*, but Pinnacle closing (PSC*) and Bet365 closing (B365C*) present.
    # Chain order puts PSC* ahead of B365C*.
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365CH,B365CD,B365CA,PSCH,PSCD,PSCA
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.80,3.60,4.50,1.88,3.65,4.35
        """,
    )
    records = load_football_data_csv(csv)
    assert records[0]["odds_source"] == "PSC"
    assert records[0]["odds_home"] == 1.88


def test_raises_when_no_odds_columns(tmp_path):
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR
        E0,12/08/23,Arsenal,Chelsea,2,1,H
        """,
    )
    with pytest.raises(ValueError):
        load_football_data_csv(csv)


def test_applies_normalizer(tmp_path):
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA
        E0,12/08/23,  Arsenal  ,Chelsea,2,1,H,1.90,3.70,4.20
        """,
    )
    # Default is str.strip -> whitespace trimmed.
    records = load_football_data_csv(csv)
    assert records[0]["home_team"] == "Arsenal"
    # Custom normalizer is honored.
    records = load_football_data_csv(csv, normalize=lambda s: s.strip().upper())
    assert records[0]["home_team"] == "ARSENAL"


def test_does_not_sort(tmp_path):
    # The parser must return rows in file order; sorting is the orchestrator's job.
    csv = _write(
        tmp_path,
        "epl.csv",
        """
        Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgCH,AvgCD,AvgCA
        E0,26/12/23,Liverpool,Burnley,1,0,H,1.30,5.00,9.00
        E0,12/08/23,Arsenal,Chelsea,2,1,H,1.90,3.70,4.20
        """,
    )
    records = load_football_data_csv(csv)
    assert [r["home_team"] for r in records] == ["Liverpool", "Arsenal"]
