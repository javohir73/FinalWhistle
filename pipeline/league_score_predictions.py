"""League score predictions grading pass ("Beat the AI's scoreline", design
doc: 2026-07-24-league-score-predictions-design.md). Scores every locked
LeagueScorePrediction on a finished football-league match under the SAME
5-exact/2-result rule app/api/league_score_predictions.py's _score_prediction
computes live for the model's side of the you-vs-AI comparison -- ported
here (duplicated, not imported -- see below) so the two numbers can never
disagree. A separate module/table from pipeline.learning_loop's
PredictionResult grading pass, which grades the MODEL's own predictions --
this one grades HUMAN picks. Mirrors pipeline/sports/nrl_user_tips.py's shape
(the proven NRL beat-the-AI grading pattern) but lives directly under
pipeline/, not pipeline/sports/ -- football pipeline modules (generate_
predictions.py, learning_loop.py, compute_club_elo.py) already live here;
pipeline/sports/ is the NRL/Origin sport-abstraction layer this feature does
not use.

Runs as a step inside pipeline/run_pipeline.py's _run_league_pipeline, right
after the model's own learning_loop step -- NOT its own GitHub workflow like
NRL's nrl-refresh.yml, since the football league pipeline already runs daily
via the existing refresh.yml (see run_pipeline.py's own module docstring).
Global, not per-league: LeagueScorePrediction rows are matched to Match rows
by match_id regardless of tournament, so one call already covers every
active league in a single pass (mirrors pipeline.learning_loop's own
tournament-agnostic queries).

Scoring (design doc, Super-6-compatible): 5 points for an exact score, 2 for
the correct result direction (win/draw/loss), 0 otherwise -- NOT cumulative.
See _score_prediction (duplicated from app/api/league_score_predictions.py's
function of the same name -- this module must not import app.api, the same
boundary nrl_user_tips.py's docstring states for its own _scores_point).

Idempotent by recompute, not by existence: every finished match's
predictions are recomputed each run and written ONLY when the computed
(points, exact) differ from what's already stored (or the row has never been
graded) -- so a normal re-run is a no-op, but a rare post-hoc score
correction on an already-"finished" match still lands correctly (unlike
pipeline.learning_loop.evaluate_finished_predictions' once-only guard, which
never revisits a match once a PredictionResult exists). graded_at is
(re)stamped only on an actual write.

INTEGRITY belt-and-braces: a prediction's updated_at must be <= the match's
kickoff_utc to be eligible at all, and a match with no kickoff_utc recorded
is never eligible either (mirrors nrl_user_tips.grade()'s identical filter).
A prediction that somehow slipped through either gap is EXCLUDED, not scored
zero: left permanently ungraded (points/exact/graded_at stay NULL) -- the
same "skip, don't half-score" convention app.api.league_score_predictions.
_kickoff_locked_prediction uses for a stray post-kickoff model row. A match
missing a final score (abandoned, per the design doc's edge cases) is
likewise never graded -- see _final_score.

CLI: python -m pipeline.league_score_predictions --grade
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import LeagueScorePrediction, Match

log = logging.getLogger(__name__)


def _final_score(m: Match) -> tuple[int, int] | None:
    """The basis for grading a finished match: the frozen 90-minute score
    when present, else the final score -- duplicated from app/api/
    league_score_predictions.py's function of the same name (see module
    docstring on why this file doesn't import app.api)."""
    h = m.score_home_90 if m.score_home_90 is not None else m.score_home
    a = m.score_away_90 if m.score_away_90 is not None else m.score_away
    if h is None or a is None:
        return None
    return h, a


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def _score_prediction(
    pred_home: int, pred_away: int, actual_home: int, actual_away: int,
) -> tuple[int, bool]:
    """(points, exact) -- 5 for an exact score, 2 for the correct result
    direction (win/draw/loss), 0 otherwise -- NOT cumulative (design doc).
    Duplicated from app/api/league_score_predictions.py's function of the
    same name so the two numbers can never disagree."""
    if pred_home == actual_home and pred_away == actual_away:
        return 5, True
    if _outcome(pred_home, pred_away) == _outcome(actual_home, actual_away):
        return 2, False
    return 0, False


def grade(db: Session) -> int:
    """Grade every locked LeagueScorePrediction on a finished Match.
    Recomputes every eligible prediction each run and writes only when the
    result differs from what's stored -- see module docstring for why this
    is idempotent without an existence guard. Returns the number of
    LeagueScorePrediction rows written this run (0 on a normal re-run)."""
    finished = db.query(Match).filter_by(status="finished").all()
    if not finished:
        return 0

    match_ids = [m.id for m in finished]
    preds = (
        db.query(LeagueScorePrediction)
        .filter(LeagueScorePrediction.match_id.in_(match_ids))
        .all()
    )
    if not preds:
        return 0

    preds_by_match: dict[int, list[LeagueScorePrediction]] = {}
    for p in preds:
        preds_by_match.setdefault(p.match_id, []).append(p)

    written = 0
    now = datetime.now(timezone.utc)
    for m in finished:
        match_preds = preds_by_match.get(m.id)
        if not match_preds:
            continue
        actual = _final_score(m)
        if actual is None:
            continue  # abandoned/no-score match: grade null, never scored (design doc edge case)
        actual_home, actual_away = actual

        for pred in match_preds:
            if m.kickoff_utc is None or pred.updated_at > m.kickoff_utc:
                continue  # belt-and-braces: no kickoff to check against, or submitted after

            points, exact = _score_prediction(pred.predicted_home, pred.predicted_away, actual_home, actual_away)
            if pred.graded_at is not None and pred.points == points and pred.exact == exact:
                continue  # already graded to the current result -- no-op

            pred.points = points
            pred.exact = exact
            pred.graded_at = now
            written += 1

    db.commit()
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grade", action="store_true",
                     help="grade locked league score predictions on finished matches")
    args = ap.parse_args()

    if not args.grade:
        ap.error("pass --grade")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        n = grade(db)
        log.info("grade: %d league score prediction row(s) graded", n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
