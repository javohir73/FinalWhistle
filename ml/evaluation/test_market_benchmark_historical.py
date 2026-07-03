"""Offline end-to-end test for the historical --csv market benchmark.

Mirrors ``pipeline.run_market_benchmark.run_historical`` WITHOUT any network:
instead of ``download_results_df()`` (which hits the martj42 GitHub mirror) it
feeds a hand-built results DataFrame through the same load -> replay -> join ->
benchmark pipeline, proving the harness is runnable before real Kaggle closing
odds exist. The committed sample fixture (ml/evaluation/fixtures/
wc2018_sample_odds.csv) supplies the odds side.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.models import Team
from ml.evaluation.backtest import is_world_cup_final_match, model_probs
from ml.evaluation.market_benchmark import benchmark, format_report, join_odds_to_rows
from pipeline.backtest_data import build_enriched_rows
from pipeline.ingest.historical_results import load_historical
from pipeline.run_market_benchmark import load_odds_csv
from pipeline.team_mapping import normalize_team_name

FIXTURE = Path(__file__).parent / "fixtures" / "wc2018_sample_odds.csv"


def _sample_df() -> pd.DataFrame:
    """Results in the historical_results schema (same columns as the ingest test).

    The two 2018 rows MUST match the fixture's (date, teams): France 4-2 Croatia
    (2018-07-15) and Belgium 2-0 England (2018-07-14). The older internationals
    give the four sides real, divergent Elo before 2018 so the model probs are
    not a trivial 50/50 coin flip.
    """
    rows = [
        # --- the two benchmarked 2018 World Cup matches (match the fixture) ---
        {"date": "2018-07-15", "home_team": "France", "away_team": "Croatia",
         "home_score": 4, "away_score": 2, "tournament": "FIFA World Cup",
         "city": "Moscow", "country": "Russia", "neutral": "TRUE"},
        {"date": "2018-07-14", "home_team": "Belgium", "away_team": "England",
         "home_score": 2, "away_score": 0, "tournament": "FIFA World Cup",
         "city": "Saint Petersburg", "country": "Russia", "neutral": "TRUE"},
        # --- older internationals among the same four teams (rating history) ---
        {"date": "2014-06-15", "home_team": "France", "away_team": "England",
         "home_score": 2, "away_score": 1, "tournament": "Friendly",
         "city": "Paris", "country": "France", "neutral": "FALSE"},
        {"date": "2015-03-27", "home_team": "Belgium", "away_team": "Croatia",
         "home_score": 1, "away_score": 1, "tournament": "Friendly",
         "city": "Brussels", "country": "Belgium", "neutral": "FALSE"},
        {"date": "2015-11-13", "home_team": "England", "away_team": "Belgium",
         "home_score": 0, "away_score": 2, "tournament": "Friendly",
         "city": "London", "country": "England", "neutral": "FALSE"},
        {"date": "2016-06-10", "home_team": "France", "away_team": "Belgium",
         "home_score": 3, "away_score": 2, "tournament": "UEFA Euro",
         "city": "Lyon", "country": "France", "neutral": "FALSE"},
        {"date": "2016-06-20", "home_team": "Croatia", "away_team": "England",
         "home_score": 1, "away_score": 2, "tournament": "UEFA Euro",
         "city": "Lille", "country": "France", "neutral": "TRUE"},
        {"date": "2017-06-13", "home_team": "France", "away_team": "England",
         "home_score": 3, "away_score": 2, "tournament": "Friendly",
         "city": "Paris", "country": "France", "neutral": "FALSE"},
        {"date": "2017-10-09", "home_team": "Croatia", "away_team": "Belgium",
         "home_score": 1, "away_score": 2, "tournament": "Friendly",
         "city": "Zagreb", "country": "Croatia", "neutral": "FALSE"},
        {"date": "2018-03-23", "home_team": "France", "away_team": "Croatia",
         "home_score": 2, "away_score": 1, "tournament": "Friendly",
         "city": "Paris", "country": "France", "neutral": "FALSE"},
    ]
    return pd.DataFrame(rows)


def test_historical_benchmark_runs_offline(db_session):
    """Full run_historical pipeline offline: load -> replay -> join -> benchmark."""
    load_historical(db_session, _sample_df())
    rows = build_enriched_rows(db_session)
    id_to_name = {t.id: t.name for t in db_session.query(Team).all()}

    target = [
        r for r in rows
        if is_world_cup_final_match(r["competition"]) and r["date"].year == 2018
    ]
    assert len(target) == 2  # sanity: both 2018 WC rows survived the replay
    for r in target:
        r["model_probs"] = model_probs(r["pre_home"], r["pre_away"], r["is_neutral"])

    odds = load_odds_csv(str(FIXTURE))
    matched, unmatched = join_odds_to_rows(
        target, odds, id_to_name, normalize=normalize_team_name
    )

    assert len(matched) >= 2
    assert unmatched == []

    res = benchmark(matched, n_bootstrap=200)
    for key in ("model", "market", "diff_log_loss", "diff_ci95"):
        assert key in res

    report = format_report(res, "WC2018 sample")
    assert "verdict:" in report


def test_load_odds_csv_skips_malformed_lines(tmp_path):
    """One valid row + one malformed row -> exactly one record parsed."""
    csv_path = tmp_path / "odds.csv"
    csv_path.write_text(
        "date,home_team,away_team,odds_home,odds_draw,odds_away\n"
        "2018-07-15,France,Croatia,1.95,3.60,4.10\n"
        "2018-07-14,Belgium,England,2.05,not_a_number,3.90\n"
    )
    records = load_odds_csv(str(csv_path))
    assert len(records) == 1
    assert records[0]["home_team"] == "France"
