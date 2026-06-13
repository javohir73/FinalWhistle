"""Match-result learning loop: evaluate finished predictions, update ratings.

The controlled, explainable update path that runs after results land
(design: tasks/design-learning-loop.md):

1. ``evaluate_finished_predictions`` — score each finished match's FROZEN
   pre-kickoff prediction (predictions are append-only and only generated
   while a match is 'scheduled', so the latest row per match is the immutable
   snapshot). Idempotent: one PredictionResult per match, written once.
2. ``update_tournament_state`` — replay ALL finished WC matches from the
   historical Elo base (ml/ratings/tournament.py) and upsert the per-team
   conservative delta + capped form adjustment. Recomputed from scratch every
   run: idempotent, drift-free, and immune to the daily base-rating rewrite.
3. ``effective_elos`` — strength map (base + delta + form) consumed by
   prediction generation and both Monte-Carlo simulators, so every surface
   moves together.

Anti-overfitting safeguards live in ml/ratings/tournament.py (damped K,
±35-Elo form cap, √n ramp) and are asserted by its tests. The double-count
guard here skips any WC match that has already been ingested into
historical_matches (the upstream dataset may add WC2026 rows mid-tournament,
which would otherwise count twice once the daily replay includes them).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import (
    HistoricalMatch,
    Match,
    Prediction,
    PredictionResult,
    Team,
    TeamTournamentState,
)
from ml.evaluation.match_metrics import evaluate_match
from ml.features.build_features import estimate_strength
from ml.ratings.elo import HOME_ADVANTAGE
from ml.ratings.tournament import TournamentMatch, replay_tournament

log = logging.getLogger(__name__)

_OUTCOME = {0: "home", 1: "draw", 2: "away"}


def _finished_matches(db: Session) -> list[Match]:
    """Finished group-stage matches with known teams and scores, kickoff order.

    Group stage only for now: knockout full-time scores from the feed may
    include extra time, which makes 90-minute outcome evaluation ambiguous —
    documented limitation, revisit at R32.
    """
    return (
        db.query(Match)
        .filter(
            Match.status == "finished",
            Match.stage == "group",
            Match.score_home.isnot(None),
            Match.score_away.isnot(None),
            Match.team_home_id.isnot(None),
            Match.team_away_id.isnot(None),
        )
        .order_by(Match.kickoff_utc.asc().nullslast(), Match.id.asc())
        .all()
    )


def _frozen_prediction(db: Session, match: Match) -> Prediction | None:
    """The pre-kickoff snapshot: latest prediction created while scheduled."""
    q = db.query(Prediction).filter(Prediction.match_id == match.id)
    if match.kickoff_utc is not None:
        q = q.filter(Prediction.created_at <= match.kickoff_utc)
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def evaluate_finished_predictions(db: Session, model_version: str) -> int:
    """Write a PredictionResult for every finished match that lacks one.

    Returns the number of NEW evaluations. Never rewrites an existing row —
    the record is append-only evidence.
    """
    evaluated_ids = {r.match_id for r in db.query(PredictionResult.match_id).all()}
    new = 0
    for m in _finished_matches(db):
        if m.id in evaluated_ids:
            continue
        pred = _frozen_prediction(db, m)
        if pred is None:
            log.warning("finished match %s has no pre-kickoff prediction; skipping", m.id)
            continue
        ev = evaluate_match(
            (pred.prob_home_win, pred.prob_draw, pred.prob_away_win),
            pred.predicted_score_home if pred.predicted_score_home is not None else -1,
            pred.predicted_score_away if pred.predicted_score_away is not None else -1,
            m.score_home,
            m.score_away,
        )
        db.add(
            PredictionResult(
                match_id=m.id,
                prediction_id=pred.id,
                model_version=pred.model_version or model_version,
                actual_score_home=m.score_home,
                actual_score_away=m.score_away,
                outcome=_OUTCOME[ev.outcome_idx],
                winner_correct=ev.winner_correct,
                exact_score_correct=ev.exact_score_correct,
                prob_assigned=(pred.prob_home_win, pred.prob_draw, pred.prob_away_win)[
                    ev.outcome_idx
                ],
                brier=ev.brier,
                log_loss=ev.log_loss,
                goal_error=ev.goal_error,
            )
        )
        new += 1
    if new:
        db.commit()
    return new


def _already_in_history(db: Session, matches: list[Match]) -> set[int]:
    """Match ids whose result already exists in historical_matches.

    The daily pipeline replays historical_matches into the base Elo; if the
    upstream dataset starts including WC2026 results, replaying them here too
    would double-count. Matched on (date, unordered team pair).
    """
    if not matches:
        return set()
    dupes: set[int] = set()
    for m in matches:
        if m.kickoff_utc is None:
            continue
        # Explicit UTC day window (±1 day for kickoff-vs-record date skew)
        # instead of func.date(), whose Postgres result depends on the
        # connection's session timezone.
        day = m.kickoff_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        lo, hi = day - timedelta(days=1), day + timedelta(days=2)
        row = (
            db.query(HistoricalMatch.id)
            .filter(
                HistoricalMatch.date >= lo,
                HistoricalMatch.date < hi,
                (
                    (HistoricalMatch.team_a_id == m.team_home_id)
                    & (HistoricalMatch.team_b_id == m.team_away_id)
                )
                | (
                    (HistoricalMatch.team_a_id == m.team_away_id)
                    & (HistoricalMatch.team_b_id == m.team_home_id)
                ),
            )
            .first()
        )
        if row is not None:
            dupes.add(m.id)
    return dupes


def update_tournament_state(db: Session) -> int:
    """Replay finished WC matches from the Elo base; upsert per-team state.

    Returns the number of teams with updated state. Teams with no finished
    matches get their state zeroed (full recompute semantics).
    """
    finished = _finished_matches(db)
    skip = _already_in_history(db, finished)

    teams = db.query(Team).all()
    base = {t.id: estimate_strength(t)[0] for t in teams}

    replay = [
        TournamentMatch(
            home_id=m.team_home_id,
            away_id=m.team_away_id,
            score_home=m.score_home,
            score_away=m.score_away,
            stage=m.stage or "group",
            home_adv=HOME_ADVANTAGE if m.host_team_id == m.team_home_id else 0.0,
        )
        for m in finished
        if m.id not in skip
    ]
    states = replay_tournament(base, replay)

    updated = 0
    for t in teams:
        st = states.get(t.id)
        row = (
            db.query(TeamTournamentState).filter_by(team_id=t.id).one_or_none()
        )
        if st is None:
            if row is not None and (row.elo_delta or row.form_adjustment):
                row.elo_delta = 0.0
                row.form_adjustment = 0.0
                row.gf_residual_mean = 0.0
                row.ga_residual_mean = 0.0
                row.matches_played = 0
                row.detail = []
            continue
        if row is None:
            row = TeamTournamentState(team_id=t.id)
            db.add(row)
        row.elo_delta = st.elo_delta
        row.form_adjustment = st.form_adjustment
        row.gf_residual_mean = st.gf_residual_mean
        row.ga_residual_mean = st.ga_residual_mean
        row.matches_played = st.matches_played
        row.detail = st.detail
        updated += 1
    db.commit()
    if skip:
        log.info("skipped %d WC matches already in historical_matches", len(skip))
    return updated


def effective_elos(db: Session) -> dict[int, float]:
    """Strength map used by prediction generation and the simulators:
    historical base + tournament Elo delta + capped form adjustment."""
    adjustments = {
        s.team_id: (s.elo_delta or 0.0) + (s.form_adjustment or 0.0)
        for s in db.query(TeamTournamentState).all()
    }
    return {
        t.id: estimate_strength(t)[0] + adjustments.get(t.id, 0.0)
        for t in db.query(Team).all()
    }


def run_learning_loop(db: Session, model_version: str) -> dict:
    """The full controlled update: evaluate, then refresh tournament state."""
    evaluated = evaluate_finished_predictions(db, model_version)
    teams_updated = update_tournament_state(db)
    summary = {"evaluated_new": evaluated, "teams_updated": teams_updated}
    log.info("learning loop: %s", summary)
    return summary


def run_post_results_chain(
    db: Session,
    model_version: str,
    n_sims: int = 2000,
    tournament_sims: int = 1000,
) -> dict:
    """Everything that should follow new results, in order: evaluate + update
    ratings → regenerate future predictions/simulations (which read the
    effective ratings) → rescore the bracket leaderboard.

    Callers clear the response cache afterwards (it's process-local, so it
    only means something inside the web process). Sim counts default lower
    than the daily pipeline's — this path runs opportunistically right after a
    final whistle, where freshness beats the last decimal of Monte-Carlo
    precision; the 06:00 UTC pipeline re-runs at full depth.
    """
    from app.scoring import recompute_scores
    from pipeline.generate_predictions import generate_predictions

    summary: dict = {"learning": run_learning_loop(db, model_version)}
    summary["predictions"] = generate_predictions(
        db, model_version, n_sims=n_sims, tournament_sims=tournament_sims
    )
    summary["brackets"] = recompute_scores(db)
    return summary
