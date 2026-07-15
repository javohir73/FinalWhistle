"""Pipeline orchestrator smoke test (task 7.6) — no network, idempotent."""
import pandas as pd

from app.models import HistoricalMatch, Prediction, Standing, Team
from pipeline.run_pipeline import run_pipeline


def _sample_results() -> pd.DataFrame:
    """A few results among real WC2026 teams so Elo/stats/predictions populate."""
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


def test_pipeline_runs_end_to_end(db_session):
    summary = run_pipeline(db_session, results_df=_sample_results(), n_sims=200)
    assert summary["structure"]["teams"] == 48
    assert summary["historical"]["matches_inserted"] > 0
    assert summary["elo"]["teams_rated"] > 0
    assert summary["predictions"]["matches_predicted"] == 72

    # Every group match has a prediction (plus its shadow twin, FR-4.4);
    # every team has a standing.
    assert db_session.query(Prediction).filter_by(is_shadow=False).count() == 72
    assert db_session.query(Prediction).filter_by(is_shadow=True).count() == 72
    assert db_session.query(Standing).count() == 48


def test_pipeline_marks_chain_covered(db_session):
    """The daily run is the catch-all sweep: after it completes, the chain
    heartbeat shows success and nothing owed (health stops flagging pending)."""
    from app.chain_status import chain_pending, get_chain_status

    run_pipeline(db_session, results_df=_sample_results(), n_sims=100)

    row = get_chain_status(db_session)
    assert row is not None and row.last_success_at is not None
    assert row.last_trigger == "pipeline"
    assert chain_pending(db_session) is False


def test_pipeline_populates_knockout_venues(db_session):
    """The daily pipeline must fill knockout venues (city/country/stadium), not
    just group-stage ones — otherwise KO match pages show a blank venue."""
    from app.models import Match

    run_pipeline(db_session, results_df=_sample_results(), n_sims=100)

    m82 = db_session.get(Match, 82)
    assert m82.venue == "Lumen Field"
    assert m82.venue_city == "Seattle"
    assert m82.venue_country == "United States"


def test_pipeline_is_idempotent(db_session):
    df = _sample_results()
    run_pipeline(db_session, results_df=df, n_sims=100)
    teams_after_first = db_session.query(Team).count()
    hist_after_first = db_session.query(HistoricalMatch).count()

    run_pipeline(db_session, results_df=df, n_sims=100)
    # Re-running must not duplicate teams or historical matches.
    assert db_session.query(Team).count() == teams_after_first
    assert db_session.query(HistoricalMatch).count() == hist_after_first


def test_pipeline_reports_prediction_coverage(db_session):
    """FR-1.2: after the predictions step, no scheduled match with teams may
    lack a frozen prediction — the coverage step proves it in the summary."""
    summary = run_pipeline(db_session, results_df=_sample_results(), n_sims=100)
    assert summary["prediction_coverage"]["missing"] == 0


def test_pipeline_runs_odds_step_only_with_api_key(db_session, monkeypatch):
    """FR-4.1/FR-6.2: the odds snapshot is a normal pipeline step when the
    API-Football key is configured, and skipped cleanly when it is not —
    the pipeline must never depend on a bookmaker feed."""
    from app.config import settings
    import pipeline.run_pipeline as rp_mod

    calls = []

    def fake_refresh(db, api_key, window_hours=48.0):
        calls.append(api_key)
        return {"matches_priced": 0, "matches_skipped": 0}

    monkeypatch.setattr("pipeline.ingest.odds.refresh_odds", fake_refresh)

    monkeypatch.setattr(settings, "api_football_api_key", "")
    summary = rp_mod.run_pipeline(db_session, results_df=_sample_results(), n_sims=100)
    assert "odds" not in summary and calls == []

    monkeypatch.setattr(settings, "api_football_api_key", "k")
    summary = rp_mod.run_pipeline(db_session, results_df=_sample_results(), n_sims=100)
    assert summary["odds"] == {"matches_priced": 0, "matches_skipped": 0}
    assert calls == ["k"]


def test_pipeline_runs_odds_backfill_step_with_api_key(db_session, monkeypatch):
    """Outage recovery: the post-match odds backfill runs right after the
    pre-kickoff snapshot when the key is configured, and is skipped cleanly
    without one — so a match whose kickoff fell inside a scheduler outage
    still gets its market consensus while the provider retains it."""
    from app.config import settings
    import pipeline.run_pipeline as rp_mod

    calls = []

    def fake_backfill(db, api_key, max_age_days=7.0):
        calls.append(api_key)
        return {"matches_priced": 0, "matches_skipped": 0}

    monkeypatch.setattr("pipeline.ingest.odds.refresh_odds",
                        lambda db, key, window_hours=48.0: {"matches_priced": 0, "matches_skipped": 0})
    monkeypatch.setattr("pipeline.ingest.odds.backfill_finished_odds", fake_backfill)

    monkeypatch.setattr(settings, "api_football_api_key", "")
    summary = rp_mod.run_pipeline(db_session, results_df=_sample_results(), n_sims=100)
    assert "odds_backfill" not in summary and calls == []

    monkeypatch.setattr(settings, "api_football_api_key", "k")
    summary = rp_mod.run_pipeline(db_session, results_df=_sample_results(), n_sims=100)
    assert summary["odds_backfill"] == {"matches_priced": 0, "matches_skipped": 0}
    assert calls == ["k"]
