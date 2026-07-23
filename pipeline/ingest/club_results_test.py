"""Tests for EPL club historical-results ingestion (league pivot D3)."""
import pandas as pd
import pytest

from app.models import HistoricalMatch, Team
from pipeline.ingest.club_results import (
    CLUB_COMPETITION,
    clean_club_results_df,
    load_club_results,
)
from pipeline.ingest.historical_results import load_historical


def _sample() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Date": "13/08/16", "HomeTeam": "Man United", "AwayTeam": "Bournemouth",
             "FTHG": 3, "FTAG": 1},
            {"Date": "20/08/16", "HomeTeam": "Nott'm Forest", "AwayTeam": "Arsenal",
             "FTHG": 0, "FTAG": 2},
            {"Date": "27/08/16", "HomeTeam": "Chelsea", "AwayTeam": "Arsenal",
             "FTHG": 2, "FTAG": 0},
        ]
    )


def test_clean_normalizes_club_aliases_and_types():
    cleaned = clean_club_results_df(_sample())
    assert "Manchester United" in set(cleaned["HomeTeam"])
    assert "Nottingham Forest" in set(cleaned["HomeTeam"])
    assert cleaned["FTHG"].dtype.kind == "i"


def test_clean_rejects_missing_columns():
    with pytest.raises(ValueError):
        clean_club_results_df(pd.DataFrame({"Date": ["13/08/16"]}))


def test_load_inserts_and_tags_club_competition(db_session):
    summary = load_club_results(db_session, _sample())
    assert summary["matches_inserted"] == 3
    assert summary["teams_created"] == 5  # Man Utd, Bournemouth, Nott'm Forest, Arsenal, Chelsea

    rows = db_session.query(HistoricalMatch).all()
    assert len(rows) == 3
    assert all(r.competition == CLUB_COMPETITION for r in rows)
    assert all(r.is_neutral is False for r in rows)

    man_utd = db_session.query(Team).filter_by(name="Manchester United").one()
    assert man_utd is not None


def test_load_is_idempotent(db_session):
    load_club_results(db_session, _sample())
    second = load_club_results(db_session, _sample())
    assert second["matches_inserted"] == 0
    assert second["skipped_dupes"] == 3
    assert db_session.query(HistoricalMatch).count() == 3


def test_club_and_international_ingest_never_collide(db_session):
    """Loading both datasets keeps them fully separable by competition, and
    neither ingest disturbs the other's rows."""
    intl = pd.DataFrame(
        [
            {"date": "2018-07-15", "home_team": "France", "away_team": "Croatia",
             "home_score": 4, "away_score": 2, "tournament": "FIFA World Cup",
             "city": "Moscow", "country": "Russia", "neutral": "TRUE"},
        ]
    )
    load_historical(db_session, intl)
    load_club_results(db_session, _sample())

    club_rows = db_session.query(HistoricalMatch).filter_by(competition=CLUB_COMPETITION).all()
    intl_rows = db_session.query(HistoricalMatch).filter(
        HistoricalMatch.competition != CLUB_COMPETITION
    ).all()
    assert len(club_rows) == 3
    assert len(intl_rows) == 1
    assert intl_rows[0].competition == "FIFA World Cup"
