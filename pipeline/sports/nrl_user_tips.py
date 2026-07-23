"""User-tips grading pass (Beat-the-AI loop, Slice 2): scores every locked
UserTip on a finished match under the same comp-standard rule the model's
own side is graded under for the you-vs-AI comparison (design doc: NRL Round
Tips, Slice 2). A separate module and a separate table from
pipeline.sports.nrl_predict.grade() -- that pass grades the MODEL's
predictions (SportPredictionResult); this one grades HUMAN picks (UserTip).
Runs as its own nrl-refresh step, right after nrl_predict --generate --grade.

Scoring (design doc, comp-standard): 1 point for a correct winner pick, or
any pick at all if the match drew. On the round's featured match only, a
tiebreak margin is also computed: |actual_margin - your_guess| if you picked
the right side, else actual_margin + your_guess (penalty). See _score_tip.

Idempotent by recompute, not by existence: every finished match's tips are
recomputed each run and written ONLY when the computed (points, round_margin)
differ from what's already stored (or the row has never been graded) -- so a
normal re-run is a no-op, but a rare post-hoc score correction on an already-
"finished" match still lands correctly (unlike nrl_predict.grade()'s once-
only guard, which never revisits a match once a SportPredictionResult
exists). graded_at is (re)stamped only on an actual write.

INTEGRITY belt-and-braces: a tip's updated_at must be <= the match's
kickoff_utc to be eligible at all (mirrors nrl_predict.grade()'s pre-kickoff
prediction filter). The submit API already rejects any post-kickoff write, so
this should never trigger in practice -- a tip that somehow slipped through
is EXCLUDED, not scored zero: it's left permanently ungraded
(points/round_margin/graded_at stay NULL), the same "skip, don't half-score"
convention app.api.nrl_tips._kickoff_locked_prediction uses for a stray
post-kickoff prediction row. There's no spare column to carry a "scored zero
but flagged invalid" marker, and the read API already treats graded_at IS
NULL as "never played this match" (GET /tips/summary's rounds only include
graded tips) -- so exclusion is the shape the existing schema/API supports.

CLI: python -m pipeline.sports.nrl_user_tips --grade
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import SportMatch, UserTip

log = logging.getLogger(__name__)

SPORT = "nrl"


def _outcome(score_home: int, score_away: int) -> str:
    """home/draw/away -- same three-way split as nrl_predict._outcome, kept
    local so this module doesn't reach into the model-grading pass."""
    if score_home > score_away:
        return "home"
    if score_home < score_away:
        return "away"
    return "draw"


def _scores_point(pick: str, outcome: str) -> bool:
    """Standard AU tipping-comp rule (design doc, Slice 2): a correct winner
    pick scores; a draw scores EVERY tipper regardless of pick. Mirrors
    app.api.nrl_user_tips._scores_point exactly (kept local -- the pipeline
    layer must not import app.api)."""
    return outcome == "draw" or pick == outcome


def _featured_match_ids(db: Session, sport: str) -> dict[tuple[int, int], int]:
    """{(season, round): featured_match_id} for every round with at least one
    match -- earliest kickoff, ties broken by match_no, the same ordering
    app.api.nrl_user_tips._featured_match_id uses per round. Computed once
    per grade() call (one query) rather than once per match."""
    rows = (
        db.query(SportMatch)
        .filter(SportMatch.sport == sport)
        .order_by(SportMatch.kickoff_utc.is_(None), SportMatch.kickoff_utc.asc(),
                  SportMatch.match_no.asc())
        .all()
    )
    featured: dict[tuple[int, int], int] = {}
    for m in rows:
        featured.setdefault((m.season, m.round), m.id)  # earliest-kickoff row wins
    return featured


def _score_tip(
    tip: UserTip, outcome: str, actual_margin: int, is_featured: bool,
) -> tuple[int, int | None]:
    """(points, round_margin) for one tip against a finished match's result.
    round_margin is only ever computed on the round's featured match, and
    only when a margin guess was actually submitted (design doc, Slice 2
    tiebreak math)."""
    correct = _scores_point(tip.pick, outcome)
    points = 1 if correct else 0
    if not is_featured or tip.margin is None:
        return points, None
    round_margin = abs(actual_margin - tip.margin) if correct else actual_margin + tip.margin
    return points, round_margin


def grade(db: Session, sport: str = SPORT) -> int:
    """Grade every locked UserTip on a finished `sport` match. Recomputes
    every eligible tip each run and writes only when the result differs from
    what's stored -- see module docstring for why this is idempotent without
    an existence guard. Returns the number of UserTip rows written this run
    (0 on a normal re-run)."""
    finished = db.query(SportMatch).filter_by(sport=sport, status="finished").all()
    if not finished:
        return 0

    match_ids = [m.id for m in finished]
    tips = db.query(UserTip).filter(UserTip.match_id.in_(match_ids)).all()
    if not tips:
        return 0

    featured_by_round = _featured_match_ids(db, sport)
    tips_by_match: dict[int, list[UserTip]] = {}
    for t in tips:
        tips_by_match.setdefault(t.match_id, []).append(t)

    written = 0
    now = datetime.now(timezone.utc)
    for m in finished:
        match_tips = tips_by_match.get(m.id)
        if not match_tips:
            continue
        outcome = _outcome(m.score_home, m.score_away)
        actual_margin = abs(m.score_home - m.score_away)
        is_featured = featured_by_round.get((m.season, m.round)) == m.id

        for tip in match_tips:
            if m.kickoff_utc is not None and tip.updated_at > m.kickoff_utc:
                continue  # belt-and-braces: shouldn't exist, never graded

            points, round_margin = _score_tip(tip, outcome, actual_margin, is_featured)
            if tip.graded_at is not None and tip.points == points and tip.round_margin == round_margin:
                continue  # already graded to the current result -- no-op

            tip.points = points
            tip.round_margin = round_margin
            tip.graded_at = now
            written += 1

    db.commit()
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grade", action="store_true", help="grade locked user tips on finished matches")
    args = ap.parse_args()

    if not args.grade:
        ap.error("pass --grade")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        n = grade(db)
        log.info("grade: %d user tip row(s) graded", n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
