"""Tests for the international Elo replay's club-competition exclusion (league
pivot D3, generalized for League Score Predictions Phase 2: the exclusion must
cover EVERY registered league's club_competition, not just EPL's single
CLUB_COMPETITION string -- see pipeline.leagues.club_competitions())."""
import pandas as pd

from app.models import HistoricalMatch, Team
from pipeline.compute_elo import compute_and_store_elo
from pipeline.ingest.club_results import load_club_results
from pipeline.ingest.historical_results import load_historical


def _seed_intl_match(db):
    argentina = Team(name="Argentina", is_host=False)
    france = Team(name="France", is_host=False)
    db.add_all([argentina, france])
    db.flush()
    db.add(
        HistoricalMatch(
            date=pd.Timestamp("2022-12-18", tz="UTC"),
            team_a_id=argentina.id, team_b_id=france.id,
            score_a=3, score_b=3, competition="FIFA World Cup", is_neutral=True,
        )
    )
    db.commit()
    return argentina.id, france.id


def test_excludes_every_registered_club_competition_not_just_epl(db_session):
    """EPL ("Premier League") AND a second league's rows (e.g. "La Liga",
    registered in pipeline.leagues.LEAGUES even though not yet active) must
    both stay out of the international replay -- a single-string `!=` check
    would let the second league leak in."""
    load_club_results(db_session, pd.DataFrame(
        [{"Date": "13/08/16", "HomeTeam": "Arsenal", "AwayTeam": "Chelsea", "FTHG": 2, "FTAG": 0}]
    ))  # EPL, default competition
    load_club_results(
        db_session,
        pd.DataFrame(
            [{"Date": "13/08/16", "HomeTeam": "Real Madrid", "AwayTeam": "Sevilla", "FTHG": 4, "FTAG": 0}]
        ),
        competition="La Liga",  # pipeline.leagues.LEAGUES["laliga"]["club_competition"]
    )
    argentina_id, _ = _seed_intl_match(db_session)

    summary = compute_and_store_elo(db_session)
    assert summary["matches_replayed"] == 1  # only the international row

    argentina = db_session.get(Team, argentina_id)
    assert argentina.elo_rating is not None

    arsenal = db_session.query(Team).filter_by(name="Arsenal").one()
    real_madrid = db_session.query(Team).filter_by(name="Real Madrid").one()
    assert arsenal.elo_rating is None  # untouched by the international replay
    assert real_madrid.elo_rating is None  # ditto -- the whole point of this test


def test_a_row_with_no_competition_recorded_still_counts_as_international(db_session):
    """NULL-safe: martj42 rows with no competition value at all are still
    international and must stay included (pre-existing behavior, preserved
    by club_competitions()'s notin_ over the registered set)."""
    load_historical(db_session, pd.DataFrame(
        [{"date": "2018-07-15", "home_team": "France", "away_team": "Croatia",
          "home_score": 4, "away_score": 2, "tournament": "FIFA World Cup",
          "city": "Moscow", "country": "Russia", "neutral": "TRUE"}]
    ))
    summary = compute_and_store_elo(db_session)
    assert summary["matches_replayed"] == 1
