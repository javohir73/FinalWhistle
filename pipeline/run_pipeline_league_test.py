"""Tests for the league (EPL 2026-27) branch of run_pipeline (league pivot D5/D7
+ League Score Predictions design doc, 2026-07-24: the configured-league-list
iteration and the score-prediction grading step)."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.config import settings
from app.models import HistoricalMatch, LeagueScorePrediction, Match, Prediction, Team, TipPlayer, Tournament
from pipeline import leagues as leagues_mod
from pipeline.ingest import league_structure as ls_mod
from pipeline.run_pipeline import run_pipeline


def _fixture(fid, home, away, status="NS", gh=None, ga=None):
    return {
        "fixture": {"id": fid, "date": "2026-08-21T19:00:00+00:00", "status": {"short": status}},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": gh, "away": ga},
    }


def _sample_wc26_results() -> pd.DataFrame:
    """A handful of results among real WC2026 teams — same shape as
    pipeline/run_pipeline_test.py's own fixture — so the WC branch's
    historical/elo/predictions steps have something to chew on."""
    teams = ["Brazil", "Argentina", "France", "Spain", "Mexico", "South Korea"]
    rows = []
    date = 2015
    for i in range(len(teams)):
        for j in range(len(teams)):
            if i == j:
                continue
            rows.append({
                "date": f"{date}-03-01", "home_team": teams[i], "away_team": teams[j],
                "home_score": (i + 1) % 4, "away_score": j % 3,
                "tournament": "Friendly", "city": "X", "country": "Y", "neutral": "TRUE",
            })
            date += 1
    return pd.DataFrame(rows)


def test_league_path_runs_the_epl_steps_and_skips_wc_only_ones(db_session, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        _fixture(1, "Arsenal", "Chelsea", status="FT", gh=2, ga=1),
        _fixture(2, "Liverpool", "Everton", status="NS"),
    ])

    summary = run_pipeline(db_session, n_sims=50)

    assert "league_structure" in summary
    assert "league_results_sync" in summary
    assert "club_elo" in summary
    assert "predictions" in summary
    assert "learning_loop" in summary
    # WC-only steps never run in this branch.
    for wc_only in ("structure", "ko_venues", "bracket_scores"):
        assert wc_only not in summary

    assert summary["league_structure"]["teams"] == 20
    assert summary["league_results_sync"]["matches_inserted"] == 1
    assert summary["club_elo"]["matches_replayed"] == 1
    assert summary["predictions"]["matches_predicted"] == 1

    tournament = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()
    assert tournament.home_advantage_mode == "home"

    arsenal = db_session.query(Team).filter_by(name="Arsenal").one()
    assert arsenal.elo_rating is not None

    scheduled_match_pred = db_session.query(Prediction).filter_by(is_shadow=False).one()
    assert scheduled_match_pred.model_version == "poisson-elo-club-v0.1"

    history_row = db_session.query(HistoricalMatch).one()
    assert history_row.competition == "Premier League"


def test_wc_path_stays_default_when_pipeline_target_unset(db_session):
    """settings.pipeline_target defaults to "wc26" — the guard clause in
    run_pipeline is a no-op unless explicitly flipped, so a run with no
    override at all takes the full WC26 sequence, not the league branch."""
    assert settings.pipeline_target == "wc26"

    summary = run_pipeline(db_session, results_df=_sample_wc26_results(), n_sims=100)

    for wc_step in ("structure", "ko_venues", "historical", "elo", "team_stats",
                    "predictions", "learning_loop", "bracket_scores", "chain_status"):
        assert wc_step in summary, f"missing WC26 step: {wc_step}"
    for league_only in ("league_structure", "league_results_sync", "club_elo"):
        assert league_only not in summary

    assert summary["structure"]["teams"] == 48
    tournament = db_session.query(Tournament).filter_by(name="FIFA World Cup 2026").one()
    assert tournament.home_advantage_mode == "host_bonus"


# ---------------------------------------------------------------------------
# League Score Predictions design doc: score-prediction grading step
# ---------------------------------------------------------------------------

def test_league_path_runs_the_score_predictions_grading_step(db_session, monkeypatch):
    """The new grading step runs after learning_loop and grades a locked,
    finished-match prediction in the same pipeline call that ingests it."""
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        _fixture(1, "Arsenal", "Chelsea", status="FT", gh=2, ga=1),
    ])

    summary = run_pipeline(db_session, n_sims=50)

    assert "score_predictions_grading" in summary
    assert summary["score_predictions_grading"] == {"graded": 0}  # nothing submitted yet -- a clean no-op

    arsenal = db_session.query(Team).filter_by(name="Arsenal").one()
    chelsea = db_session.query(Team).filter_by(name="Chelsea").one()
    finished_match = db_session.query(Match).filter_by(
        team_home_id=arsenal.id, team_away_id=chelsea.id
    ).one()
    player = TipPlayer(device_id="3fa85f64-5717-4562-b3fc-2c963f66afa6", handle="Tester")
    db_session.add(player)
    db_session.flush()
    pred = LeagueScorePrediction(
        tournament_id=finished_match.tournament_id, match_id=finished_match.id, player_id=player.id,
        predicted_home=2, predicted_away=1,
        updated_at=finished_match.kickoff_utc - timedelta(hours=1),
    )
    db_session.add(pred)
    db_session.commit()

    summary2 = run_pipeline(db_session, n_sims=50)

    assert summary2["score_predictions_grading"] == {"graded": 1}
    db_session.refresh(pred)
    assert pred.points == 5
    assert pred.exact is True


def test_league_path_grading_step_is_non_fatal_on_error(db_session, monkeypatch):
    """A grading-pass failure must never fail the rest of the (already-
    committed) model pipeline -- mirrors the WC26 branch's _prob_snapshots
    best-effort contract."""
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        _fixture(1, "Arsenal", "Chelsea", status="FT", gh=2, ga=1),
        _fixture(2, "Liverpool", "Everton", status="NS"),
    ])

    import pipeline.league_score_predictions as lsp_mod

    def _boom(db):
        raise RuntimeError("boom")

    monkeypatch.setattr(lsp_mod, "grade", _boom)

    summary = run_pipeline(db_session, n_sims=50)

    assert summary["score_predictions_grading"] == {"graded": 0, "error": True}
    # Everything upstream of the grading step still landed.
    assert summary["predictions"]["matches_predicted"] == 1
    assert summary["learning_loop"] is not None


# ---------------------------------------------------------------------------
# League Score Predictions design doc: configured league-list iteration
# ---------------------------------------------------------------------------

def test_league_pipeline_skips_unconfigured_league_code_and_continues(db_session, monkeypatch):
    """A code listed in ACTIVE_LEAGUES with no matching pipeline.leagues.
    LEAGUES entry is skipped with a warning, not a crash -- the rest of the
    (correctly configured) league list still runs. Since exactly one code
    resolves here, step names stay unprefixed (same as the single-league
    case) -- the bogus entry alongside it doesn't change that."""
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(leagues_mod, "ACTIVE_LEAGUES", ["epl", "bogus"])
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        _fixture(1, "Arsenal", "Chelsea", status="FT", gh=2, ga=1),
    ])

    summary = run_pipeline(db_session, n_sims=50)

    assert "league_structure" in summary
    assert "league_results_sync" in summary
    assert "predictions" in summary
    assert "bogus_league_structure" not in summary
    assert summary["league_structure"]["teams"] == 20
    tournament = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()
    assert tournament.id is not None


def test_league_pipeline_no_op_when_every_configured_league_is_unresolvable(db_session, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(leagues_mod, "ACTIVE_LEAGUES", ["bogus"])

    summary = run_pipeline(db_session, n_sims=50)

    assert summary == {}  # nothing ran -- no crash, no partial state
    assert db_session.query(Tournament).count() == 0


def test_league_pipeline_prefixes_step_names_once_two_leagues_are_configured(db_session, monkeypatch):
    """Phase 2 shape check: with two leagues actually resolving, the
    per-league steps (structure/results_sync/predictions) gain a "{code}_"
    prefix so their summaries don't collide -- club_elo/learning_loop/
    score_predictions_grading stay unprefixed since they were never
    tournament-scoped to begin with."""
    monkeypatch.setattr(settings, "pipeline_target", "league")
    second_league = dict(leagues_mod.LEAGUES["epl"])
    second_league["tournament_name"] = "La Liga 2026-27"
    second_league["group_name"] = "La Liga"
    second_league["league_id"] = 140
    monkeypatch.setitem(leagues_mod.LEAGUES, "laliga", second_league)
    monkeypatch.setattr(leagues_mod, "ACTIVE_LEAGUES", ["epl", "laliga"])
    monkeypatch.setattr(ls_mod, "fetch_fixtures", lambda *a, **k: [
        _fixture(1, "Arsenal", "Chelsea", status="FT", gh=2, ga=1),
    ])

    summary = run_pipeline(db_session, n_sims=50)

    for key in ("epl_league_structure", "epl_league_results_sync", "epl_predictions",
                "laliga_league_structure", "laliga_league_results_sync", "laliga_predictions"):
        assert key in summary, f"missing {key}"
    for flat_key in ("league_structure", "league_results_sync", "predictions"):
        assert flat_key not in summary
    for shared_key in ("club_elo", "learning_loop", "score_predictions_grading"):
        assert shared_key in summary

    epl = db_session.query(Tournament).filter_by(name="Premier League 2026-27").one()
    laliga = db_session.query(Tournament).filter_by(name="La Liga 2026-27").one()
    assert epl.id != laliga.id


# ---------------------------------------------------------------------------
# League Score Predictions Phase 2: the real 3-entry registry (pipeline.
# leagues.LEAGUES already has epl/laliga/bundesliga -- see pipeline/leagues.py)
# with ONLY ACTIVE_LEAGUES monkeypatched, so these exercise the actual
# registered configs rather than a synthetic copy.
# ---------------------------------------------------------------------------

def _fixture_with_ids(fid, home, home_id, away, away_id, status="NS", gh=None, ga=None):
    """Like _fixture() above but carries teams.home/away.id -- laliga/
    bundesliga's real registry entries have teams_file=None, so their teams
    are derived from the fixtures payload and need a provider id per side."""
    return {
        "fixture": {"id": fid, "date": "2026-08-21T19:00:00+00:00", "status": {"short": status}},
        "teams": {"home": {"id": home_id, "name": home}, "away": {"id": away_id, "name": away}},
        "goals": {"home": gh, "away": ga},
    }


def _three_league_fetch(api_key, league, season):
    return {
        39: [_fixture_with_ids(1, "Arsenal", 42, "Chelsea", 49, status="FT", gh=2, ga=1)],
        140: [_fixture_with_ids(2, "Real Madrid", 541, "Sevilla", 536, status="FT", gh=3, ga=0)],
        78: [_fixture_with_ids(3, "Bayern Munich", 157, "Borussia Dortmund", 165, status="FT", gh=1, ga=1)],
    }[league]


def test_league_pipeline_runs_all_three_registered_leagues(db_session, monkeypatch):
    """Every step's prefix/shared-key behavior generalizes past two leagues
    to three, and each league's club_elo replay lands on its OWN tournament
    row (recon item 3) -- not just whichever tournament happened to be
    queried first."""
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(leagues_mod, "ACTIVE_LEAGUES", ["epl", "laliga", "bundesliga"])
    monkeypatch.setattr(ls_mod, "fetch_fixtures", _three_league_fetch)

    summary = run_pipeline(db_session, n_sims=50)

    for code in ("epl", "laliga", "bundesliga"):
        for step_name in ("league_structure", "league_results_sync", "predictions"):
            assert f"{code}_{step_name}" in summary, f"missing {code}_{step_name}"
    for flat_key in ("league_structure", "league_results_sync", "predictions"):
        assert flat_key not in summary
    for shared_key in ("club_elo", "learning_loop", "score_predictions_grading"):
        assert shared_key in summary

    tournaments = {t.name: t for t in db_session.query(Tournament).all()}
    assert set(tournaments) == {"Premier League 2026-27", "La Liga 2026-27", "Bundesliga 2026-27"}
    # Each league's own fitted (here: default 60.0) home advantage landed on
    # its OWN row -- three separate writes, not one shared side effect.
    for t in tournaments.values():
        assert t.home_advantage_value == 60.0

    assert db_session.query(HistoricalMatch).filter_by(competition="Premier League").count() == 1
    assert db_session.query(HistoricalMatch).filter_by(competition="La Liga").count() == 1
    assert db_session.query(HistoricalMatch).filter_by(competition="Bundesliga").count() == 1


def test_league_pipeline_one_leagues_ingest_failure_does_not_kill_the_others(db_session, monkeypatch):
    """A bad API-Football response for exactly one configured league (La
    Liga) is logged and that league is skipped, but EPL and Bundesliga still
    run their full per-league step sequence and the shared steps still run."""
    monkeypatch.setattr(settings, "pipeline_target", "league")
    monkeypatch.setattr(leagues_mod, "ACTIVE_LEAGUES", ["epl", "laliga", "bundesliga"])

    def _flaky_fetch(api_key, league, season):
        if league == 140:  # laliga
            raise RuntimeError("api-football unreachable for La Liga")
        return _three_league_fetch(api_key, league, season)

    monkeypatch.setattr(ls_mod, "fetch_fixtures", _flaky_fetch)

    summary = run_pipeline(db_session, n_sims=50)

    assert "laliga_league_structure" not in summary
    assert "laliga_league_results_sync" not in summary
    assert "laliga_predictions" not in summary
    for code in ("epl", "bundesliga"):
        for step_name in ("league_structure", "league_results_sync", "predictions"):
            assert f"{code}_{step_name}" in summary, f"missing {code}_{step_name}"
    for shared_key in ("club_elo", "learning_loop", "score_predictions_grading"):
        assert shared_key in summary

    tournaments = {t.name for t in db_session.query(Tournament).all()}
    assert tournaments == {"Premier League 2026-27", "Bundesliga 2026-27"}
    assert db_session.query(Tournament).filter_by(name="La Liga 2026-27").count() == 0

    # The healthy leagues' data landed cleanly despite the sibling failure.
    assert db_session.query(HistoricalMatch).filter_by(competition="Premier League").count() == 1
    assert db_session.query(HistoricalMatch).filter_by(competition="Bundesliga").count() == 1
    assert db_session.query(HistoricalMatch).filter_by(competition="La Liga").count() == 0
