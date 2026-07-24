"""Tests for club historical-results ingestion (league pivot D3; multi-division
as of League Score Predictions Phase 2)."""
from pathlib import Path

import pandas as pd
import pytest

from app.models import HistoricalMatch, Team
from pipeline.ingest import league_structure as ls_mod
from pipeline.ingest.club_results import (
    BASE_URL,
    CLUB_COMPETITION,
    DEFAULT_DIVISION,
    clean_club_results_df,
    download_club_results_df,
    load_club_results,
    sync_finished_matches_to_history,
)
from pipeline.ingest.historical_results import load_historical
from pipeline.ingest.league_structure import load_league_structure

TESTDATA = Path(__file__).parent / "testdata"


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


def test_sync_finished_matches_mirrors_in_season_results(db_session, monkeypatch):
    """In-season results (only ever Match rows, no CSV yet) sync into
    historical_matches idempotently, tagged CLUB_COMPETITION."""
    from app.models import Tournament

    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        {
            "fixture": {"id": 1, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "FT"}},
            "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
            "goals": {"home": 2, "away": 1},
        },
        {
            "fixture": {"id": 2, "date": "2026-08-22T14:00:00+00:00", "status": {"short": "NS"}},
            "teams": {"home": {"name": "Liverpool"}, "away": {"name": "Everton"}},
            "goals": {"home": None, "away": None},
        },
    ])
    load_league_structure(db_session, api_key="x")
    tournament = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()

    summary = sync_finished_matches_to_history(db_session, tournament)
    assert summary["matches_inserted"] == 1  # only the finished fixture

    row = db_session.query(HistoricalMatch).filter_by(competition=CLUB_COMPETITION).one()
    assert row.score_a == 2 and row.score_b == 1
    assert row.is_neutral is False

    # Idempotent: re-running (e.g. next pipeline tick) inserts nothing new.
    second = sync_finished_matches_to_history(db_session, tournament)
    assert second["matches_inserted"] == 0
    assert db_session.query(HistoricalMatch).filter_by(competition=CLUB_COMPETITION).count() == 1


# ---------------------------------------------------------------------------
# Config-driven multi-division download (League Score Predictions Phase 2:
# SP1 = La Liga, D1 = Bundesliga). DEFAULT_DIVISION (E0) keeps every call
# above this line byte-for-byte unaffected -- these tests exercise the new
# `division`/`competition` parameters explicitly.
# ---------------------------------------------------------------------------

def test_default_division_is_still_e0():
    """A bare download_club_results_df() call must stay EPL -- no behavior
    change for existing (unparameterized) callers."""
    assert DEFAULT_DIVISION == "E0"
    assert BASE_URL.format(season="2526", division=DEFAULT_DIVISION) == (
        "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
    )


def test_download_club_results_df_builds_the_url_per_division(monkeypatch):
    """SP1/D1 (and any other division code) plug into the SAME URL shape as
    E0 -- only the division segment changes."""
    requested_urls: list[str] = []
    real_read_csv = pd.read_csv

    def _fake_read_csv(url, *a, **k):
        requested_urls.append(url)
        return real_read_csv(TESTDATA / "sp1_sample.csv")

    monkeypatch.setattr(pd, "read_csv", _fake_read_csv)
    download_club_results_df(season_codes=["1617", "2526"], division="SP1")

    assert requested_urls == [
        "https://www.football-data.co.uk/mmz4281/1617/SP1.csv",
        "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
    ]


def test_load_sp1_and_d1_samples_tag_their_own_club_competition(db_session):
    """Small SP1/D1 sample CSVs (pipeline/ingest/testdata) parse and load the
    same way E0's do, each tagged with its OWN competition discriminator --
    matching pipeline.leagues.LEAGUES["laliga"/"bundesliga"]["club_competition"]."""
    sp1_df = pd.read_csv(TESTDATA / "sp1_sample.csv")
    d1_df = pd.read_csv(TESTDATA / "d1_sample.csv")

    sp1_summary = load_club_results(db_session, sp1_df, competition="La Liga")
    assert sp1_summary["matches_inserted"] == 3

    d1_summary = load_club_results(db_session, d1_df, competition="Bundesliga")
    assert d1_summary["matches_inserted"] == 3

    laliga_rows = db_session.query(HistoricalMatch).filter_by(competition="La Liga").all()
    bundesliga_rows = db_session.query(HistoricalMatch).filter_by(competition="Bundesliga").all()
    assert len(laliga_rows) == 3
    assert len(bundesliga_rows) == 3
    # "Bayern Munich" (football-data.co.uk's D1 spelling) normalizes to
    # "Bayern München" (team_mapping.py's SP1/D1 alias, API-Football's own
    # spelling) rather than being locked in unchanged -- that reconciliation
    # is the whole point of the alias table (Opus review, League Score
    # Predictions Phase 2): a Team row named "Bayern Munich" would never be
    # the one a fixtures-derived roster/predictions read.
    assert {t.name for t in db_session.query(Team).all()} == {
        "Real Madrid", "Sevilla", "Barcelona", "Valencia",
        "Bayern München", "Werder Bremen", "Hoffenheim",
    }


def test_multi_league_club_rows_never_collide_across_competitions(db_session):
    """Three leagues sharing historical_matches (EPL default + La Liga +
    Bundesliga) stay fully separable by competition, mirroring
    test_club_and_international_ingest_never_collide's EPL/international
    isolation check one level up -- now club-vs-club too."""
    load_club_results(db_session, _sample())  # EPL, default competition
    load_club_results(db_session, pd.read_csv(TESTDATA / "sp1_sample.csv"), competition="La Liga")
    load_club_results(db_session, pd.read_csv(TESTDATA / "d1_sample.csv"), competition="Bundesliga")

    assert db_session.query(HistoricalMatch).filter_by(competition=CLUB_COMPETITION).count() == 3
    assert db_session.query(HistoricalMatch).filter_by(competition="La Liga").count() == 3
    assert db_session.query(HistoricalMatch).filter_by(competition="Bundesliga").count() == 3
    assert db_session.query(HistoricalMatch).count() == 9


def test_load_is_idempotent_per_competition(db_session):
    """Idempotency (existing-key dedup) is scoped per competition -- reloading
    La Liga's sample after Bundesliga's is already loaded inserts La Liga's 3
    rows fresh, not "0 skipped" from Bundesliga's unrelated rows."""
    load_club_results(db_session, pd.read_csv(TESTDATA / "d1_sample.csv"), competition="Bundesliga")
    first = load_club_results(db_session, pd.read_csv(TESTDATA / "sp1_sample.csv"), competition="La Liga")
    assert first["matches_inserted"] == 3
    assert first["skipped_dupes"] == 0

    second = load_club_results(db_session, pd.read_csv(TESTDATA / "sp1_sample.csv"), competition="La Liga")
    assert second["matches_inserted"] == 0
    assert second["skipped_dupes"] == 3


def test_sync_finished_matches_scopes_to_the_passed_competition(db_session, monkeypatch):
    """sync_finished_matches_to_history's competition kwarg must be honored,
    not silently default to CLUB_COMPETITION for a non-EPL tournament."""
    from app.models import Tournament

    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        {
            "fixture": {"id": 501, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "FT"}},
            "teams": {"home": {"id": 541, "name": "Real Madrid"}, "away": {"id": 536, "name": "Sevilla"}},
            "goals": {"home": 3, "away": 0},
        },
    ])
    load_league_structure(
        db_session, teams_file=None, api_key="x",
        tournament_name="La Liga 2026-27", group_name="La Liga",
        league_id=140, season=2026,
    )
    tournament = db_session.query(Tournament).filter_by(name="La Liga 2026-27").one()

    summary = sync_finished_matches_to_history(db_session, tournament, competition="La Liga")
    assert summary["matches_inserted"] == 1

    row = db_session.query(HistoricalMatch).filter_by(competition="La Liga").one()
    assert row.score_a == 3 and row.score_b == 0
    # Never landed under the EPL default -- a stray bug here would silently
    # blend La Liga's history into EPL's club Elo replay.
    assert db_session.query(HistoricalMatch).filter_by(competition=CLUB_COMPETITION).count() == 0


# ---------------------------------------------------------------------------
# Provider-name reconciliation (Opus review, League Score Predictions Phase
# 2): API-Football's fixtures payload (what load_league_structure seeds the
# roster from, teams_file=None) and football-data.co.uk's SP1/D1 CSVs (what
# THIS module backfills) spell some Spanish/German clubs differently. Without
# a team_mapping alias, load_club_results would create a SECOND, Elo-less
# "ghost" Team row for the same real-world club instead of landing on the one
# generate_predictions actually reads -- the exact "attach a result to the
# wrong club" failure this ingest exists to prevent.
# ---------------------------------------------------------------------------

def test_fixtures_and_csv_club_names_reconcile_onto_a_single_team_row(db_session, monkeypatch):
    """Atletico Madrid: API-Football's fixtures payload spells it out in full
    (what the roster/predictions use); football-data.co.uk's SP1 convention
    is "Ath Madrid" (team_mapping.py's SP1 alias). Both must land on ONE Team
    row, with the CSV's history reaching the SAME row the roster seeded."""
    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [
            {
                "fixture": {"id": 9401, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "NS"}},
                "teams": {"home": {"id": 530, "name": "Atletico Madrid"}, "away": {"id": 541, "name": "Real Madrid"}},
                "goals": {"home": None, "away": None},
            },
        ],
    )
    load_league_structure(
        db_session, teams_file=None, api_key="x",
        tournament_name="La Liga 2026-27", group_name="La Liga",
        league_id=140, season=2026,
    )
    assert db_session.query(Team).filter_by(name="Atletico Madrid").count() == 1

    sp1_df = pd.DataFrame(
        [
            {"Date": "13/08/16", "HomeTeam": "Ath Madrid", "AwayTeam": "Real Madrid",
             "FTHG": 2, "FTAG": 1},
            {"Date": "20/08/16", "HomeTeam": "Real Madrid", "AwayTeam": "Ath Madrid",
             "FTHG": 0, "FTAG": 0},
        ]
    )
    load_club_results(db_session, sp1_df, competition="La Liga")

    # No ghost "Ath Madrid" row -- the CSV's history landed on the SAME Team
    # the fixtures payload seeded.
    assert db_session.query(Team).filter_by(name="Atletico Madrid").count() == 1
    assert db_session.query(Team).filter_by(name="Ath Madrid").count() == 0

    from pipeline.compute_club_elo import compute_and_store_club_elo, unrated_roster_teams

    compute_and_store_club_elo(db_session, competition="La Liga", tournament_name="La Liga 2026-27")
    atletico = db_session.query(Team).filter_by(name="Atletico Madrid").one()
    # The replay's rating landed on the SAME row predictions read -- not a
    # separate, Elo-less ghost.
    assert atletico.elo_rating is not None
    assert unrated_roster_teams(db_session, "La Liga 2026-27", "La Liga") == []
