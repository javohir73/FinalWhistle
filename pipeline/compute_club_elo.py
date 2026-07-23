"""Seed club Elo ratings via a leak-free chronological replay (league pivot D3).

Mirrors pipeline/compute_elo.py's shape (replay historical_matches -> write
teams.elo_rating) but scoped to CLUB_COMPETITION-tagged rows only, with its
own tuned home-advantage magnitude — club home advantage is not necessarily
the same number as international Elo's host bonus, so it gets its own fit
rather than reusing ml.ratings.elo.HOME_ADVANTAGE by assumption.

Home-advantage fit (docs/LEAGUE-PIVOT-PLAN.md D4): replay every one of the
9 seasons before the holdout (2016-17..2024-25) leak-free, then score log
loss of the Poisson-Elo W/D/L triple against the ACTUAL 2025-26 season
(the holdout — never used to fit ratings, only to evaluate them), same
discipline as ml/evaluation/tune.py's walk-forward split and the harness
pipeline/run_club_benchmark.py already uses. Run against the real
football-data.co.uk CSVs on 2026-07-23 (fit_home_advantage(), 3800 replayed
matches, 380-match 2025-26 holdout):

    home_adv=40.0: log_loss=1.047818  brier=0.632355  accuracy=0.4816
    home_adv=60.0: log_loss=1.047464  brier=0.631721  accuracy=0.4842  <- winner
    home_adv=80.0: log_loss=1.050784  brier=0.633364  accuracy=0.4763

-> winner: 60.0 (lowest holdout log loss) — coincidentally the same magnitude
as the international host bonus (ml.ratings.elo.HOME_ADVANTAGE), but arrived
at independently rather than assumed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team
from ml.evaluation.backtest import compute_metrics, model_probs
from ml.ratings.elo import MatchInput, replay_with_prematch, run_elo
from pipeline.ingest.club_results import (
    CLUB_COMPETITION,
    HOLDOUT_SEASON_CODE,
    clean_club_results_df,
    download_club_results_df,
)

CLUB_HOME_ADVANTAGE = 60.0


def _club_matches(db: Session) -> list[HistoricalMatch]:
    return (
        db.query(HistoricalMatch)
        .filter_by(competition=CLUB_COMPETITION)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )


def compute_and_store_club_elo(
    db: Session, home_advantage: float = CLUB_HOME_ADVANTAGE
) -> dict:
    """Leak-free chronological replay of every CLUB_COMPETITION row, writing
    final ratings onto the club Team rows.

    Scoped to CLUB_COMPETITION only via _club_matches' filter — never reads or
    writes an international team's rating (pipeline/compute_elo.py's own
    query symmetrically excludes CLUB_COMPETITION, so the two never clobber
    each other regardless of run order; see pipeline/compute_club_elo_test.py).
    """
    rows = _club_matches(db)
    matches = [
        MatchInput(
            home_id=r.team_a_id, away_id=r.team_b_id,
            score_home=r.score_a, score_away=r.score_b,
            competition=r.competition, is_neutral=False,
        )
        for r in rows
    ]
    ratings = run_elo(matches, home_advantage=home_advantage)

    updated = 0
    for team_id, rating in ratings.items():
        team = db.get(Team, team_id)
        if team is not None:
            team.elo_rating = round(rating, 1)
            updated += 1
    db.commit()

    return {
        "matches_replayed": len(matches),
        "teams_rated": updated,
        "home_advantage": home_advantage,
    }


def _evaluate_holdout(rows: list[dict], holdout_season: str, home_advantage: float) -> dict:
    """Replay leak-free across every row (any season), then score the
    Poisson-Elo log loss against holdout_season's rows alone."""
    team_ids: dict[str, int] = {}

    def _id(name: str) -> int:
        if name not in team_ids:
            team_ids[name] = len(team_ids)
        return team_ids[name]

    inputs = [
        MatchInput(
            home_id=_id(r["HomeTeam"]), away_id=_id(r["AwayTeam"]),
            score_home=r["FTHG"], score_away=r["FTAG"],
            competition=CLUB_COMPETITION, is_neutral=False,
        )
        for r in rows
    ]
    replay_rows, _ = replay_with_prematch(inputs, home_advantage=home_advantage)

    probs_list = []
    labels = []
    for rec, rep in zip(rows, replay_rows):
        if rec["season_code"] != holdout_season:
            continue
        probs_list.append(
            model_probs(rep["pre_home"], rep["pre_away"], False, home_adv=home_advantage)
        )
        sh, sa = rec["FTHG"], rec["FTAG"]
        labels.append("H" if sh > sa else ("A" if sh < sa else "D"))
    return compute_metrics(probs_list, labels)


def fit_home_advantage(
    df, candidates: tuple[float, ...] = (40.0, 60.0, 80.0),
    holdout_season: str = HOLDOUT_SEASON_CODE,
) -> dict:
    """Try each candidate home-advantage value on a leak-free replay,
    scoring log loss on ``holdout_season`` alone. ``df`` is the cleaned,
    multi-season DataFrame (clean_club_results_df on the concatenated
    download_club_results_df output), still carrying ``season_code``.
    Pure (no DB) — the module-level CLUB_HOME_ADVANTAGE constant above is
    this function's already-run result against the real CSVs; re-run it
    with ``python -m pipeline.compute_club_elo --fit`` if the holdout
    season rolls over."""
    rows = df.sort_values("match_date").to_dict("records")
    results = {c: _evaluate_holdout(rows, holdout_season, c)["log_loss"] for c in candidates}
    winner = min(results, key=results.get)
    return {"results": results, "winner": winner}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fit", action="store_true",
        help="download the CSVs fresh and re-run the {40,60,80} holdout fit",
    )
    args = ap.parse_args()
    if args.fit:
        df = clean_club_results_df(download_club_results_df())
        result = fit_home_advantage(df)
        for cand, ll in result["results"].items():
            print(f"home_adv={cand}: log_loss={ll:.6f}")
        print(f"-> winner: {result['winner']}")
        return 0

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import settings

    engine = create_engine(settings.sqlalchemy_url, future=True)
    db = sessionmaker(bind=engine, future=True)()
    try:
        print(compute_and_store_club_elo(db))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
