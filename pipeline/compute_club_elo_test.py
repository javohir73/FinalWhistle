"""Tests for club Elo seeding + the international/club scoping regression
(league pivot D3)."""
import pandas as pd

from app.models import HistoricalMatch, Team, Tournament
from pipeline.compute_club_elo import compute_and_store_club_elo, fit_home_advantage, unrated_roster_teams
from pipeline.compute_elo import compute_and_store_elo
from pipeline.generate_predictions import _host_adv
from pipeline.ingest.club_results import CLUB_COMPETITION, load_club_results
from pipeline.ingest.league_structure import TOURNAMENT_NAME


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


def test_persists_fitted_home_advantage_onto_the_tournament_row(db_session):
    """Opus review of PR #171, item 3: without this, EPL's Tournament row
    keeps home_advantage_value NULL forever, so _host_adv silently falls back
    to the international engine's params.home_adv instead of the club-tuned
    magnitude."""
    from pipeline.ingest.league_structure import load_league_structure

    _seed_club_matches(db_session)
    load_league_structure(db_session, api_key="x")  # creates the Tournament row
    tournament = db_session.query(Tournament).filter_by(name=TOURNAMENT_NAME).one()
    assert tournament.home_advantage_value is None  # nothing fitted yet

    summary = compute_and_store_club_elo(db_session, home_advantage=60.0)
    db_session.refresh(tournament)
    assert tournament.home_advantage_value == 60.0
    assert summary["home_advantage"] == 60.0

    # And _host_adv now prefers it over an unrelated engine default, end to end.
    from app.models import Match

    match = Match(
        tournament_id=tournament.id, stage="group", status="scheduled",
        team_home_id=db_session.query(Team).filter_by(name="Arsenal").one().id,
        team_away_id=db_session.query(Team).filter_by(name="Chelsea").one().id,
        is_neutral=False,
    )
    db_session.add(match)
    db_session.commit()
    home = db_session.get(Team, match.team_home_id)
    assert _host_adv(match, home, home_advantage=999.0) == 60.0


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


# ---------------------------------------------------------------------------
# Per-league generalization (League Score Predictions Phase 2, recon item 3):
# competition/tournament_name became keyword parameters so >1 league can share
# historical_matches without their replays or home_advantage_value writes
# clobbering each other. EPL's bare-call behavior above (test_replays_only_
# club_rows_and_writes_elo, test_persists_fitted_home_advantage_onto_the_
# tournament_row) is the "EPL numbers reproduced identically" regression --
# both already pass unmodified with every default preserved.
# ---------------------------------------------------------------------------

def test_per_league_replay_and_home_advantage_write_are_isolated(db_session):
    """A second league (synthetic 'La Liga', sharing historical_matches with
    EPL) gets its own replay scope and its own Tournament's
    home_advantage_value -- neither call touches the other's ratings or the
    other's tournament row, and re-running EPL's replay doesn't move the
    second league's rating."""
    from pipeline.ingest.club_results import load_club_results

    _seed_club_matches(db_session)  # EPL rows, default competition

    laliga_df = pd.DataFrame(
        [
            {"Date": "13/08/16", "HomeTeam": "Real Madrid", "AwayTeam": "Sevilla",
             "FTHG": 4, "FTAG": 0},
            {"Date": "20/08/16", "HomeTeam": "Sevilla", "AwayTeam": "Real Madrid",
             "FTHG": 1, "FTAG": 3},
        ]
    )
    load_club_results(db_session, laliga_df, competition="La Liga")

    epl_tournament = Tournament(
        name="Premier League 2026-27", year=2026, host_countries="", home_advantage_mode="home",
    )
    laliga_tournament = Tournament(
        name="La Liga 2026-27", year=2026, host_countries="", home_advantage_mode="home",
    )
    db_session.add_all([epl_tournament, laliga_tournament])
    db_session.commit()

    epl_summary = compute_and_store_club_elo(db_session)  # bare call -- every default unchanged
    assert epl_summary["matches_replayed"] == 3
    assert epl_summary["home_advantage"] == 60.0

    laliga_summary = compute_and_store_club_elo(
        db_session, home_advantage=45.0, competition="La Liga", tournament_name="La Liga 2026-27",
    )
    assert laliga_summary["matches_replayed"] == 2
    assert laliga_summary["home_advantage"] == 45.0

    db_session.refresh(epl_tournament)
    db_session.refresh(laliga_tournament)
    assert epl_tournament.home_advantage_value == 60.0
    assert laliga_tournament.home_advantage_value == 45.0  # not clobbered by the EPL call

    real_madrid = db_session.query(Team).filter_by(name="Real Madrid").one()
    assert real_madrid.elo_rating is not None
    real_madrid_rating = real_madrid.elo_rating

    # Re-running EPL's replay (still the bare default call) must not move
    # La Liga's rating or its tournament's home_advantage_value.
    compute_and_store_club_elo(db_session)
    db_session.refresh(real_madrid)
    db_session.refresh(laliga_tournament)
    assert real_madrid.elo_rating == real_madrid_rating
    assert laliga_tournament.home_advantage_value == 45.0


# ---------------------------------------------------------------------------
# unrated_roster_teams (Opus review, League Score Predictions Phase 2): the
# reconciliation check for a Phase 2 league's roster -- a club whose Team row
# never received the replayed club Elo (almost always a missing
# team_mapping alias between API-Football's fixtures spelling and football-
# data.co.uk's CSV spelling) must surface here before the league is trusted.
# ---------------------------------------------------------------------------

def test_unrated_roster_teams_flags_a_club_the_backfill_never_reached(db_session, monkeypatch):
    from pipeline.ingest import league_structure as ls_mod
    from pipeline.ingest.league_structure import load_league_structure

    monkeypatch.setattr(
        ls_mod, "fetch_fixtures",
        lambda *a, **k: [
            {
                "fixture": {"id": 9402, "date": "2026-08-21T19:00:00+00:00", "status": {"short": "NS"}},
                "teams": {
                    "home": {"id": 530, "name": "Atletico Madrid"},
                    "away": {"id": 999, "name": "Some Newly Promoted FC"},
                },
                "goals": {"home": None, "away": None},
            },
        ],
    )
    load_league_structure(
        db_session, teams_file=None, api_key="x",
        tournament_name="La Liga 2026-27", group_name="La Liga",
        league_id=140, season=2026,
    )
    # Only Atletico Madrid (via its "Ath Madrid" alias) has any backfilled
    # history -- the newly-promoted club has none at all yet.
    sp1_df = pd.DataFrame(
        [{"Date": "13/08/16", "HomeTeam": "Ath Madrid", "AwayTeam": "Sevilla", "FTHG": 2, "FTAG": 1}]
    )
    load_club_results(db_session, sp1_df, competition="La Liga")

    compute_and_store_club_elo(db_session, competition="La Liga", tournament_name="La Liga 2026-27")

    assert unrated_roster_teams(db_session, "La Liga 2026-27", "La Liga") == ["Some Newly Promoted FC"]


def test_unrated_roster_teams_returns_empty_for_an_unknown_tournament_or_group(db_session):
    """Nothing to check yet (league_structure hasn't run) -- never raises."""
    assert unrated_roster_teams(db_session, "Not A Real League 2026-27", "Not A Real Group") == []
