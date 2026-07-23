"""Tests for club Elo seeding + the international/club scoping regression
(league pivot D3)."""
import pandas as pd

from app.models import HistoricalMatch, Team
from pipeline.compute_club_elo import compute_and_store_club_elo, fit_home_advantage
from pipeline.compute_elo import compute_and_store_elo
from pipeline.ingest.club_results import CLUB_COMPETITION, load_club_results


def _seed_club_matches(db):
    df = pd.DataFrame(
        [
            {"Date": "13/08/16", "HomeTeam": "Arsenal", "AwayTeam": "Liverpool",
             "FTHG": 3, "FTAG": 1},
            {"Date": "20/08/16", "HomeTeam": "Liverpool", "AwayTeam": "Arsenal",
             "FTHG": 1, "FTAG": 1},
            {"Date": "27/08/16", "HomeTeam": "Arsenal", "AwayTeam": "Chelsea",
             "FTHG": 2, "FTAG": 0},
        ]
    )
    load_club_results(db, df)


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


def test_replays_only_club_rows_and_writes_elo(db_session):
    _seed_club_matches(db_session)
    summary = compute_and_store_club_elo(db_session)
    assert summary["matches_replayed"] == 3
    assert summary["home_advantage"] == 60.0

    arsenal = db_session.query(Team).filter_by(name="Arsenal").one()
    assert arsenal.elo_rating is not None
    assert arsenal.elo_rating != 1500.0


def test_international_recompute_never_touches_club_ratings(db_session):
    """Regression: club Elo survives a daily international recompute, and
    vice versa — the two rewrites are scoped to disjoint HistoricalMatch
    rows (competition=CLUB_COMPETITION vs everything else)."""
    _seed_club_matches(db_session)
    argentina_id, france_id = _seed_intl_match(db_session)

    compute_and_store_club_elo(db_session)
    arsenal = db_session.query(Team).filter_by(name="Arsenal").one()
    club_rating_after_club_run = arsenal.elo_rating
    argentina = db_session.get(Team, argentina_id)
    assert argentina.elo_rating is None  # untouched — no international run yet

    # International recompute must not clobber the club rating just written.
    compute_and_store_elo(db_session)
    db_session.refresh(arsenal)
    assert arsenal.elo_rating == club_rating_after_club_run
    argentina = db_session.get(Team, argentina_id)
    assert argentina.elo_rating is not None  # now rated by the international replay

    # And the reverse: re-running club Elo must not touch the international rating.
    intl_rating_after_intl_run = argentina.elo_rating
    compute_and_store_club_elo(db_session)
    db_session.refresh(argentina)
    assert argentina.elo_rating == intl_rating_after_intl_run


def test_fit_home_advantage_picks_the_lowest_holdout_log_loss():
    from pipeline.ingest.club_results import clean_club_results_df

    rows = []
    teams = ["Arsenal", "Chelsea", "Liverpool", "Everton"]
    day = 1
    for season in ("1617", "2526"):
        for i in range(8):
            home, away = teams[i % 4], teams[(i + 1) % 4]
            rows.append({
                "Date": f"{day:02d}/08/{'16' if season == '1617' else '25'}",
                "HomeTeam": home, "AwayTeam": away,
                "FTHG": (i % 3), "FTAG": ((i + 1) % 3),
                "season_code": season,  # download_club_results_df tags this per-season
            })
            day += 1
    df = clean_club_results_df(pd.DataFrame(rows))

    result = fit_home_advantage(df, candidates=(40.0, 60.0, 80.0), holdout_season="2526")
    assert set(result["results"]) == {40.0, 60.0, 80.0}
    assert result["winner"] == min(result["results"], key=result["results"].get)
