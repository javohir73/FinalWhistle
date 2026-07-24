"""Seed club Elo ratings via a leak-free chronological replay (league pivot D3;
per-league as of League Score Predictions Phase 2).

Mirrors pipeline/compute_elo.py's shape (replay historical_matches -> write
teams.elo_rating) but scoped to one league's club_competition-tagged rows at a
time, with its own tuned home-advantage magnitude — club home advantage is not
necessarily the same number as international Elo's host bonus (or another
league's own club home advantage), so each league gets its own fit rather than
reusing ml.ratings.elo.HOME_ADVANTAGE, or another league's CLUB_HOME_ADVANTAGE,
by assumption.

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
at independently rather than assumed. CLUB_HOME_ADVANTAGE below is this
result for EPL specifically (division="E0") -- La Liga/Bundesliga each need
their OWN fit_home_advantage() run against their own SP1/D1 CSVs (a separate,
data-integrity-gated follow-up: never assume 60.0 carries over) before
compute_and_store_club_elo should be called with anything other than its
default for those leagues.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HistoricalMatch, Team, Tournament
from ml.evaluation.backtest import compute_metrics, model_probs
from ml.ratings.elo import MatchInput, replay_with_prematch, run_elo
from pipeline.ingest.club_results import (
    CLUB_COMPETITION,
    HOLDOUT_SEASON_CODE,
    clean_club_results_df,
    download_club_results_df,
)
from pipeline.ingest.league_structure import TOURNAMENT_NAME

# EPL's fitted value (see the module docstring). The module-level default for
# compute_and_store_club_elo, so every existing (EPL) caller is unaffected.
CLUB_HOME_ADVANTAGE = 60.0


def _club_matches(db: Session, competition: str = CLUB_COMPETITION) -> list[HistoricalMatch]:
    return (
        db.query(HistoricalMatch)
        .filter_by(competition=competition)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )


def compute_and_store_club_elo(
    db: Session,
    home_advantage: float = CLUB_HOME_ADVANTAGE,
    *,
    competition: str = CLUB_COMPETITION,
    tournament_name: str = TOURNAMENT_NAME,
) -> dict:
    """Leak-free chronological replay of every ``competition``-tagged row,
    writing final ratings onto the club Team rows. Every default is EPL's own
    (CLUB_COMPETITION/TOURNAMENT_NAME/CLUB_HOME_ADVANTAGE), so a bare
    compute_and_store_club_elo(db) call is byte-for-byte unchanged; Phase 2
    leagues pass their own pipeline.leagues.LEAGUES[...] values instead --
    see pipeline/run_pipeline.py's per-league club_elo step.

    Scoped to ``competition`` only via _club_matches' filter — never reads or
    writes another league's (or the international replay's) rating
    (pipeline/compute_elo.py's own query symmetrically excludes every
    registered club_competition, so none of them ever clobber each other
    regardless of run order; see pipeline/compute_club_elo_test.py).

    Also persists ``home_advantage`` onto the ``tournament_name`` Tournament
    row's home_advantage_value (Opus review of PR #171, item 3): _host_adv
    (pipeline/generate_predictions.py) already prefers that column over the
    international engine's params.home_adv fallback whenever it's set, but
    league_structure.py's loader leaves it NULL at creation — without writing
    it here, a league would silently start tracking whatever params.home_adv
    is tuned to internationally if that value is ever retuned, instead of its
    own fitted magnitude (or whatever ``home_advantage`` this call used).
    """
    rows = _club_matches(db, competition=competition)
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

    tournament = db.query(Tournament).filter_by(name=tournament_name).one_or_none()
    if tournament is not None:
        tournament.home_advantage_value = home_advantage

    db.commit()

    return {
        "matches_replayed": len(matches),
        "teams_rated": updated,
        "home_advantage": home_advantage,
    }


def _evaluate_holdout(
    rows: list[dict], holdout_season: str, home_advantage: float, competition: str = CLUB_COMPETITION
) -> dict:
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
            competition=competition, is_neutral=False,
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
    *,
    competition: str = CLUB_COMPETITION,
) -> dict:
    """Try each candidate home-advantage value on a leak-free replay,
    scoring log loss on ``holdout_season`` alone. ``df`` is the cleaned,
    multi-season DataFrame (clean_club_results_df on the concatenated
    download_club_results_df(division=...) output), still carrying
    ``season_code``. Pure (no DB) — the module-level CLUB_HOME_ADVANTAGE
    constant above is this function's already-run result against the real
    EPL CSVs; re-run it with ``python -m pipeline.compute_club_elo --fit``
    if the holdout season rolls over, or against a Phase 2 league's own
    SP1/D1 CSVs (passing its own ``competition``) before trusting a fitted
    value for that league — 60.0 is EPL's number, not an assumed default for
    every league."""
    rows = df.sort_values("match_date").to_dict("records")
    results = {
        c: _evaluate_holdout(rows, holdout_season, c, competition=competition)["log_loss"]
        for c in candidates
    }
    winner = min(results, key=results.get)
    return {"results": results, "winner": winner}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fit", action="store_true",
        help="download the CSVs fresh and re-run the {40,60,80} holdout fit",
    )
    ap.add_argument(
        "--division", default="E0",
        help="football-data.co.uk division code (default E0=EPL; SP1=La Liga, D1=Bundesliga)",
    )
    ap.add_argument(
        "--competition", default=CLUB_COMPETITION,
        help="historical_matches.competition discriminator for --division (default: EPL's)",
    )
    args = ap.parse_args()
    if args.fit:
        df = clean_club_results_df(download_club_results_df(division=args.division))
        result = fit_home_advantage(df, competition=args.competition)
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
