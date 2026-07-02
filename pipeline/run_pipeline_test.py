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

    # Every group match has a prediction; every team has a standing.
    assert db_session.query(Prediction).count() == 72
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


def test_pipeline_is_idempotent(db_session):
    df = _sample_results()
    run_pipeline(db_session, results_df=df, n_sims=100)
    teams_after_first = db_session.query(Team).count()
    hist_after_first = db_session.query(HistoricalMatch).count()

    run_pipeline(db_session, results_df=df, n_sims=100)
    # Re-running must not duplicate teams or historical matches.
    assert db_session.query(Team).count() == teams_after_first
    assert db_session.query(HistoricalMatch).count() == hist_after_first
