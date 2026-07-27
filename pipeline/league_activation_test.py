from datetime import datetime, timezone

import pandas as pd
import pytest

from app.models import HistoricalMatch, Team
from pipeline.league_activation import ensure_club_history
from pipeline.leagues import LEAGUES


def _config(minimum=2):
    return {**LEAGUES["laliga"], "history_min_matches": minimum}


def _frame():
    return pd.DataFrame(
        [
            {"Date": "01/08/25", "HomeTeam": "Celta", "AwayTeam": "Sociedad", "FTHG": 1, "FTAG": 0},
            {"Date": "02/08/25", "HomeTeam": "Vallecano", "AwayTeam": "Espanol", "FTHG": 2, "FTAG": 2},
        ]
    )


def test_fresh_database_downloads_loads_and_reconciles_names(db_session):
    result = ensure_club_history(
        db_session,
        _config(),
        downloader=lambda **_kwargs: _frame(),
    )

    assert result["downloaded"] is True
    assert result["matches"] == 2
    assert {
        team.name for team in db_session.query(Team).all()
    } == {"Celta Vigo", "Real Sociedad", "Rayo Vallecano", "Espanyol"}


def test_complete_database_skips_network(db_session):
    home = Team(name="Home")
    away = Team(name="Away")
    db_session.add_all([home, away])
    db_session.flush()
    for day in (1, 2):
        db_session.add(
            HistoricalMatch(
                date=datetime(2025, 8, day, tzinfo=timezone.utc),
                team_a_id=home.id,
                team_b_id=away.id,
                score_a=1,
                score_b=0,
                competition="La Liga",
                is_neutral=False,
            )
        )
    db_session.commit()

    result = ensure_club_history(
        db_session,
        _config(),
        downloader=lambda **_kwargs: pytest.fail("network should not be called"),
    )

    assert result == {
        "competition": "La Liga",
        "matches": 2,
        "downloaded": False,
        "minimum": 2,
    }


def test_truncated_source_fails_before_predictions(db_session):
    with pytest.raises(RuntimeError, match="historical backfill incomplete"):
        ensure_club_history(
            db_session,
            _config(minimum=3),
            downloader=lambda **_kwargs: _frame(),
        )
