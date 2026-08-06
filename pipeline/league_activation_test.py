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


def test_ucl_uses_explicit_api_football_history_strategy(db_session):
    calls = []

    def downloader(**kwargs):
        calls.append(kwargs)
        return [
            {
                "fixture_id": 100,
                "date": datetime(2025, 9, 17, tzinfo=timezone.utc),
                "home_id": 42,
                "home_name": "Arsenal",
                "away_id": 541,
                "away_name": "Real Madrid",
                "score_home": 2,
                "score_away": 1,
                "is_neutral": False,
            }
        ]

    config = {**LEAGUES["ucl"], "history_min_matches": 1}
    result = ensure_club_history(db_session, config, downloader=downloader)

    assert result["matches"] == 1
    assert calls == [
        {
            "api_key": "",
            "league": 2,
            "seasons": (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025),
        }
    ]
    assert db_session.query(HistoricalMatch).filter_by(
        competition="UEFA Champions League"
    ).count() == 1


# --- Widening an already-satisfied history window -----------------------------
# ensure_club_history short-circuits on ROW COUNT, not on "which seasons are
# loaded". So adding editions to history_seasons does nothing on its own once a
# league is already above its minimum — the threshold has to move too, or the
# wider window is config that never executes. These pin that coupling.

def test_widening_history_seasons_needs_the_minimum_raised_to_take_effect(db_session):
    """The trap: with the OLD minimum still in place, a league already holding
    enough rows returns early and the new editions are never fetched."""
    already_enough = [
        HistoricalMatch(
            date=datetime(2024, 9, day, tzinfo=timezone.utc),
            team_a_id=1, team_b_id=2, score_a=1, score_b=0,
            competition="UEFA Champions League", is_neutral=False,
        )
        for day in (1, 2, 3)
    ]
    db_session.add_all([Team(name="A"), Team(name="B")])
    db_session.flush()
    db_session.add_all(already_enough)
    db_session.commit()

    config = {**LEAGUES["ucl"], "history_min_matches": 2}  # below what's stored
    result = ensure_club_history(
        db_session, config,
        downloader=lambda **_k: pytest.fail("must not fetch while above minimum"),
    )
    assert result["downloaded"] is False


def test_ucl_minimum_exceeds_the_four_edition_window_it_replaces(db_session):
    """The shipped minimum must sit ABOVE the row count the previous
    four-edition window produced (988 rows, 2026-08-01 activation card), or the
    widened window would be inert on every database that already ran the old
    backfill — including production."""
    assert LEAGUES["ucl"]["history_min_matches"] > 988


def test_ucl_minimum_leaves_headroom_under_the_real_eight_edition_total(db_session):
    """...and BELOW the real total, with margin: falling short raises and skips
    the league's predictions entirely. Measured 2026-08-06 across the eight
    configured editions: 1,810 finished regulation-time fixtures."""
    assert LEAGUES["ucl"]["history_min_matches"] <= 1700
