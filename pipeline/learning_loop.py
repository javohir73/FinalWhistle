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

from app.chain_status import (
    finished_match_count,
    finished_matches_query,
    record_attempt,
    record_failure,
    record_success,
)
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
    """ALL finished matches with known teams and scores, in kickoff order —
    group and knockout stages alike, so the loop is a true catch-all.

    Knockout convention: the stored score is the feed's final score — after
    extra time when played, never counting shootout kicks — the same basis
    every user-facing verdict uses (frontend/lib/verdict.ts). A tie decided
    on penalties is level, so it evaluates and replays as a draw, matching
    the model's 90-minute basis (shootouts are deliberately unmodelled). The
    one accepted skew: for the WINNER verdict and the Elo replay, a tie
    decided by an extra-time goal counts at its after-ET score rather than
    the 90-minute draw. EXACT-SCORE hits, by contrast, score against the
    captured 90-minute basis when present (FR-2.2; evaluate_match's
    exact_home_goals/exact_away_goals), matching the frontend verdict's
    scoreline comparison.
    Eligibility (finished + teams + scores) is shared with the chain-status
    watermark (app/chain_status.finished_matches_query) so "pending" counts
    exactly what this loop sweeps.
    """
    return (
        finished_matches_query(db)
        .order_by(Match.kickoff_utc.asc().nullslast(), Match.id.asc())
        .all()
    )


def _frozen_prediction(db: Session, match: Match, *, shadow: bool = False) -> Prediction | None:
    """The pre-kickoff snapshot: latest prediction created while scheduled.

    Production and shadow rows are frozen SEPARATELY (FR-4.5): the audited
    record must never pick up an odds-anchored twin, and the shadow record
    must never pick up a production row.
    """
    q = db.query(Prediction).filter(
        Prediction.match_id == match.id,
        Prediction.is_shadow.is_(shadow),
    )
    if match.kickoff_utc is not None:
        q = q.filter(Prediction.created_at <= match.kickoff_utc)
    return q.order_by(Prediction.created_at.desc(), Prediction.id.desc()).first()


def _result_row(m: Match, pred: Prediction, model_version: str, *, shadow: bool) -> PredictionResult:
    """Evaluate one frozen prediction against a finished match — the SAME math
    for the production record and the shadow record (FR-4.6)."""
    ev = evaluate_match(
        (pred.prob_home_win, pred.prob_draw, pred.prob_away_win),
        pred.predicted_score_home if pred.predicted_score_home is not None else -1,
        pred.predicted_score_away if pred.predicted_score_away is not None else -1,
        m.score_home,
        m.score_away,
        # Exact-score on the 90-minute basis when captured (FR-2.2); the
        # winner verdict keeps the after-ET final-result convention.
        exact_home_goals=m.score_home_90,
        exact_away_goals=m.score_away_90,
    )
    return PredictionResult(
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
        is_shadow=shadow,
    )


def evaluate_finished_predictions(db: Session, model_version: str) -> int:
    """Write a PredictionResult for every finished match that lacks one.

    Returns the number of NEW evaluations. Never rewrites an existing row —
    the record is append-only evidence.
    """
    evaluated_ids = {
        r.match_id
        for r in db.query(PredictionResult.match_id)
        .filter(PredictionResult.is_shadow.is_(False))
        .all()
    }
    new = 0
    for m in _finished_matches(db):
        if m.id in evaluated_ids:
            continue
        pred = _frozen_prediction(db, m)
        if pred is None:
            log.warning("finished match %s has no pre-kickoff prediction; skipping", m.id)
            continue
        db.add(_result_row(m, pred, model_version, shadow=False))
        new += 1
    if new:
        db.commit()
    return new


def evaluate_finished_shadow_predictions(db: Session) -> int:
    """Score the shadow model's frozen predictions into is_shadow=True result
    rows (FR-4.6) — the data behind /api/internal/shadow-record. Matches with
    no shadow twin (pre-Phase-4) are skipped silently: no twin, no comparison.
    Append-only and idempotent, exactly like the production path.
    """
    evaluated_ids = {
        r.match_id
        for r in db.query(PredictionResult.match_id)
        .filter(PredictionResult.is_shadow.is_(True))
        .all()
    }
    new = 0
    for m in _finished_matches(db):
        if m.id in evaluated_ids:
            continue
        pred = _frozen_prediction(db, m, shadow=True)
        if pred is None:
            continue
        db.add(_result_row(m, pred, pred.model_version, shadow=True))
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
    from ml.models.params import load_params

    served = load_params()
    states = replay_tournament(
        base, replay, goals_base=served.base, goals_beta=served.beta
    )

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
    """The full controlled update: evaluate (production, then shadow — the
    shadow record never feeds ratings), then refresh tournament state."""
    evaluated = evaluate_finished_predictions(db, model_version)
    shadow_evaluated = evaluate_finished_shadow_predictions(db)
    teams_updated = update_tournament_state(db)
    summary = {
        "evaluated_new": evaluated,
        "shadow_evaluated_new": shadow_evaluated,
        "teams_updated": teams_updated,
    }
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
    from app.scoring import recompute_scores, knockout_results_from_db
    from pipeline.backfill_90min import backfill_90min_scores
    from pipeline.generate_predictions import generate_predictions

    # Heal 90-minute scores BEFORE evaluating: result rows are append-only, so
    # a match evaluated on the wrong basis can never be re-scored — the
    # goal-events reconstruction must run first (cheap: NULL rows only).
    summary: dict = {"backfill_90min": backfill_90min_scores(db)}
    summary["learning"] = run_learning_loop(db, model_version)
    summary["predictions"] = generate_predictions(
        db, n_sims=n_sims, tournament_sims=tournament_sims
    )
    summary["brackets"] = recompute_scores(db, knockout_results=knockout_results_from_db(db))
    return summary


def run_tracked_post_results_chain(
    db: Session,
    model_version: str,
    *,
    trigger: str,
    n_sims: int = 2000,
    tournament_sims: int = 1000,
) -> dict:
    """``run_post_results_chain`` with a durable heartbeat (app/chain_status).

    Records the attempt before the heavy work (committed, so even a killed
    process leaves a trace), and advances the success watermark ONLY after the
    full chain completed — a crash or an OOM-kill mid-run leaves the finished
    matches marked pending, which later refreshes and the daily pipeline use
    to retry. Failures are recorded and re-raised: swallow-or-500 is the
    caller's policy, the bookkeeping is not.
    """
    covered = finished_match_count(db)  # taken BEFORE: a mid-run finish stays owed
    record_attempt(db, trigger)
    try:
        summary = run_post_results_chain(
            db, model_version, n_sims=n_sims, tournament_sims=tournament_sims
        )
    except Exception as exc:
        db.rollback()  # drop any partial, uncommitted stage before the status write
        record_failure(db, exc)
        raise
    record_success(db, covered)
    return summary
