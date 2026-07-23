"""Tests for the league (EPL 2026-27) branch of run_pipeline (league pivot D5/D7)."""
from app.config import settings
from app.models import HistoricalMatch, Prediction, Team, Tournament
from pipeline.ingest import league_structure as ls_mod
from pipeline.run_pipeline import run_pipeline


def _fixture(fid, home, away, status="NS", gh=None, ga=None):
    return {
        "fixture": {"id": fid, "date": "2026-08-21T19:00:00+00:00", "status": {"short": status}},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": gh, "away": ga},
    }


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
    run_pipeline is a no-op unless explicitly flipped."""
    assert settings.pipeline_target == "wc26"
