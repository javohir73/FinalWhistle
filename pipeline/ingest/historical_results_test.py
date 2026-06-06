"""Tests for historical results ingestion (task 2.10)."""
import pandas as pd

from app.models import HistoricalMatch, Team
from pipeline.ingest.historical_results import clean_results_df, load_historical


def _sample() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2022-12-18", "home_team": "Argentina", "away_team": "France",
             "home_score": 3, "away_score": 3, "tournament": "FIFA World Cup",
             "city": "Lusail", "country": "Qatar", "neutral": "TRUE"},
            {"date": "2018-07-15", "home_team": "France", "away_team": "Croatia",
             "home_score": 4, "away_score": 2, "tournament": "FIFA World Cup",
             "city": "Moscow", "country": "Russia", "neutral": "TRUE"},
            {"date": "1990-07-08", "home_team": "West Germany", "away_team": "Argentina",
             "home_score": 1, "away_score": 0, "tournament": "FIFA World Cup",
             "city": "Rome", "country": "Italy", "neutral": "TRUE"},
        ]
    )


def test_clean_normalizes_names_and_types():
    cleaned = clean_results_df(_sample())
    assert "Germany" in set(cleaned["home_team"])  # West Germany -> Germany
    assert cleaned["home_score"].dtype.kind == "i"
    assert cleaned["neutral"].all()


def test_clean_rejects_missing_columns():
    import pytest

    with pytest.raises(ValueError):
        clean_results_df(pd.DataFrame({"date": ["2020-01-01"]}))


def test_load_inserts_and_creates_teams(db_session):
    summary = load_historical(db_session, _sample())
    assert summary["matches_inserted"] == 3
    # Argentina, France, Croatia, Germany = 4 unique teams (West Germany merged)
    assert db_session.query(Team).count() == 4
    assert db_session.query(HistoricalMatch).count() == 3


def test_load_is_idempotent(db_session):
    load_historical(db_session, _sample())
    second = load_historical(db_session, _sample())
    assert second["matches_inserted"] == 0
    assert second["skipped_dupes"] == 3
    assert db_session.query(HistoricalMatch).count() == 3
