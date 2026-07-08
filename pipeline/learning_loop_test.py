"""Integration tests for the match-result learning loop (brief task 9).

Covers: rating updates after a completed match, no update without results,
winner/exact-score metric storage, the form-layer cap, future predictions
actually changing after a meaningful result, idempotence, the
historical-matches double-count guard, and the post-results chain (including
leaderboard rescoring).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.chain_status import chain_pending, get_chain_status
from app.models import (
    HistoricalMatch,
    Match,
    Prediction,
    PredictionResult,
    Team,
    TeamTournamentState,
)
from ml.ratings.tournament import FORM_CAP_ELO
from pipeline.generate_predictions import generate_predictions
from pipeline.ingest.wc26_structure import load_structure
from pipeline.learning_loop import (
    build_seed_ledgers,
    effective_elos,
    evaluate_finished_predictions,
    run_learning_loop,
    run_post_results_chain,
    run_tracked_post_results_chain,
    update_tournament_state,
)

MV = "poisson-elo-v0.1"


def _set_elos(db):
    for i, t in enumerate(db.query(Team).order_by(Team.id).all()):
        t.elo_rating = 1500.0 + (i % 12) * 40
    db.commit()


def _seed(db, n_sims=120):
    """Structure + ratings + a full set of pre-kickoff predictions."""
    load_structure(db)
    _set_elos(db)
    generate_predictions(db, MV, n_sims=n_sims, tournament_sims=50)


def _finish(db, match: Match, score_home: int, score_away: int):
    """Finish a match the way live ingestion does, with a realistic timeline:
    prediction made before kickoff, kickoff in the past, result now in."""
    kickoff = datetime.now(timezone.utc) - timedelta(hours=3)
    match.kickoff_utc = kickoff
    for p in db.query(Prediction).filter_by(match_id=match.id).all():
        p.created_at = kickoff - timedelta(days=1)
    match.status = "finished"
    match.score_home = score_home
    match.score_away = score_away
    db.commit()


def _first_group_match(db) -> Match:
    return (
        db.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .order_by(Match.id)
        .first()
    )


def _production_result(db) -> PredictionResult:
    """The single PRODUCTION result row (shadow twins are scored separately —
    their isolation is covered in pipeline/shadow_predictions_test.py)."""
    return db.query(PredictionResult).filter_by(is_shadow=False).one()


def test_no_update_without_finished_matches(db_session):
    _seed(db_session)
    summary = run_learning_loop(db_session, MV)
    assert summary == {"evaluated_new": 0, "shadow_evaluated_new": 0, "teams_updated": 0}
    assert db_session.query(PredictionResult).count() == 0
    # Effective ratings equal the base when there is no tournament evidence.
    base = {t.id: t.elo_rating for t in db_session.query(Team).all()}
    assert effective_elos(db_session) == base


def test_completed_match_updates_ratings_and_stores_metrics(db_session):
    _seed(db_session)
    m = _first_group_match(db_session)
    pred = (
        db_session.query(Prediction)
        .filter_by(match_id=m.id)
        .order_by(Prediction.id.desc())
        .first()
    )
    # Finish it exactly as predicted: winner + exact score must both register.
    _finish(db_session, m, pred.predicted_score_home, pred.predicted_score_away)

    summary = run_learning_loop(db_session, MV)
    assert summary["evaluated_new"] == 1
    assert summary["teams_updated"] == 2

    r = _production_result(db_session)
    assert r.match_id == m.id
    assert r.exact_score_correct is True
    assert r.goal_error == 0
    assert 0.0 <= r.brier <= 2.0 and r.log_loss > 0

    # Both teams now carry state, zero-sum deltas.
    sh = db_session.query(TeamTournamentState).filter_by(team_id=m.team_home_id).one()
    sa = db_session.query(TeamTournamentState).filter_by(team_id=m.team_away_id).one()
    assert sh.matches_played == 1 and sa.matches_played == 1
    assert abs(sh.elo_delta + sa.elo_delta) < 1e-6
    assert abs(sh.form_adjustment) <= FORM_CAP_ELO


def test_upset_is_recorded_as_miss_and_loop_is_idempotent(db_session):
    _seed(db_session)
    m = _first_group_match(db_session)
    pred = (
        db_session.query(Prediction).filter_by(match_id=m.id)
        .order_by(Prediction.id.desc()).first()
    )
    # Make the LESS likely side win emphatically.
    if pred.prob_home_win >= pred.prob_away_win:
        _finish(db_session, m, 0, 3)
        loser_id = m.team_home_id
    else:
        _finish(db_session, m, 3, 0)
        loser_id = m.team_away_id

    run_learning_loop(db_session, MV)
    first = _production_result(db_session)
    assert first.winner_correct is False

    loser = db_session.query(TeamTournamentState).filter_by(team_id=loser_id).one()
    assert loser.elo_delta < 0
    # Conservative: even a 3-goal upset stays a nudge, not a rewrite.
    assert abs(loser.elo_delta) < 60
    delta_before = loser.elo_delta

    # Second run: nothing double-applies, nothing re-evaluates.
    summary = run_learning_loop(db_session, MV)
    assert summary["evaluated_new"] == 0
    assert db_session.query(PredictionResult).filter_by(is_shadow=False).count() == 1
    db_session.refresh(loser)
    assert abs(loser.elo_delta - delta_before) < 1e-9


def test_form_cap_holds_under_absurd_blowouts(db_session):
    _seed(db_session)
    matches = (
        db_session.query(Match)
        .filter(Match.stage == "group", Match.team_home_id.isnot(None))
        .order_by(Match.id).limit(3).all()
    )
    # One team annihilates everyone 9-0 three times: the form layer must clamp.
    for m in matches:
        _finish(db_session, m, 9, 0)
    run_learning_loop(db_session, MV)
    for s in db_session.query(TeamTournamentState).all():
        assert abs(s.form_adjustment) <= FORM_CAP_ELO + 1e-9


def test_future_predictions_move_after_meaningful_result(db_session):
    _seed(db_session)
    m = _first_group_match(db_session)
    home_id = m.team_home_id

    # The home side's NEXT fixture, before any results.
    future = (
        db_session.query(Match)
        .filter(
            Match.stage == "group", Match.status == "scheduled",
            Match.id != m.id,
            (Match.team_home_id == home_id) | (Match.team_away_id == home_id),
        )
        .order_by(Match.id).first()
    )
    before = (
        db_session.query(Prediction).filter_by(match_id=future.id)
        .order_by(Prediction.id.desc()).first()
    )
    p_home_before = (
        before.prob_home_win if future.team_home_id == home_id else before.prob_away_win
    )

    # Heavy defeat for the home side, then the full controlled update.
    _finish(db_session, m, 0, 4)
    run_learning_loop(db_session, MV)
    generate_predictions(db_session, MV, n_sims=120, tournament_sims=50)

    after = (
        db_session.query(Prediction).filter_by(match_id=future.id)
        .order_by(Prediction.id.desc()).first()
    )
    p_home_after = (
        after.prob_home_win if future.team_home_id == home_id else after.prob_away_win
    )
    # The beaten side's future win probability must drop — and explainably so,
    # not collapse (conservative update).
    assert p_home_after < p_home_before
    assert p_home_before - p_home_after < 0.15


def test_double_count_guard_skips_matches_already_in_history(db_session):
    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 2, 0)
    # Upstream dataset already ingested this result -> replay must skip it.
    db_session.add(
        HistoricalMatch(
            date=m.kickoff_utc,
            team_a_id=m.team_home_id,
            team_b_id=m.team_away_id,
            score_a=2,
            score_b=0,
            competition="FIFA World Cup",
            is_neutral=False,
        )
    )
    db_session.commit()

    update_tournament_state(db_session)
    states = db_session.query(TeamTournamentState).filter(
        TeamTournamentState.matches_played > 0
    ).count()
    assert states == 0  # nothing replayed -> no double counting


def _seed_with_drawn_ko_match(db) -> Match:
    """Structure + ratings, an R32 tie with real teams drawn, then predictions
    (so the KO tie gets its pre-kickoff snapshot like any drawn KO match)."""
    load_structure(db)
    _set_elos(db)
    ko = db.query(Match).filter(Match.stage == "R32").order_by(Match.id).first()
    home, away = db.query(Team).order_by(Team.id).limit(2).all()
    ko.team_home_id, ko.team_away_id = home.id, away.id
    db.commit()
    generate_predictions(db, MV, n_sims=120, tournament_sims=50)
    return ko


def test_finished_knockout_match_is_evaluated_and_updates_ratings(db_session):
    """The daily catch-all must not stop at the group stage: a finished R32
    match gets a PredictionResult and feeds the rating replay (stage-weighted)."""
    ko = _seed_with_drawn_ko_match(db_session)
    _finish(db_session, ko, 2, 0)

    summary = run_learning_loop(db_session, MV)

    assert summary["evaluated_new"] == 1
    r = _production_result(db_session)
    assert r.match_id == ko.id
    assert r.outcome == "home"

    sh = db_session.query(TeamTournamentState).filter_by(team_id=ko.team_home_id).one()
    sa = db_session.query(TeamTournamentState).filter_by(team_id=ko.team_away_id).one()
    assert sh.matches_played == 1 and sa.matches_played == 1
    assert abs(sh.elo_delta + sa.elo_delta) < 1e-6
    assert sh.detail[0]["stage"] == "R32"


def test_shootout_tie_scores_as_regulation_draw(db_session):
    """Level after extra time, decided on penalties: the stored score stays
    level and the shootout tally must count as neither goals nor a win — the
    tie evaluates and replays as a draw (the model's 90-minute basis)."""
    ko = _seed_with_drawn_ko_match(db_session)
    _finish(db_session, ko, 1, 1)
    ko.penalty_home, ko.penalty_away = 3, 4
    db_session.commit()

    summary = run_learning_loop(db_session, MV)

    assert summary["evaluated_new"] == 1
    r = _production_result(db_session)
    assert r.outcome == "draw"
    assert (r.actual_score_home, r.actual_score_away) == (1, 1)

    # Zero-sum replay: the shootout winner gets no Elo credit for the kicks.
    sh = db_session.query(TeamTournamentState).filter_by(team_id=ko.team_home_id).one()
    sa = db_session.query(TeamTournamentState).filter_by(team_id=ko.team_away_id).one()
    assert abs(sh.elo_delta + sa.elo_delta) < 1e-6
    assert sh.detail[0]["score"] == "1-1"


def test_post_results_chain_runs_end_to_end_and_rescores(db_session):
    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 1, 0)

    summary = run_post_results_chain(db_session, MV, n_sims=120, tournament_sims=50)
    assert summary["learning"]["evaluated_new"] == 1
    assert summary["predictions"]["matches_predicted"] > 0
    assert "brackets" in summary  # leaderboard rescoring ran (0 brackets is fine)
    assert db_session.query(PredictionResult).filter_by(is_shadow=False).count() == 1


def test_tracked_chain_writes_success_watermark(db_session):
    """A COMPLETED chain records success and covers the finished-match count,
    so retry triggers know nothing is owed."""
    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 1, 0)
    assert chain_pending(db_session) is True  # a finish nothing has covered yet

    summary = run_tracked_post_results_chain(
        db_session, MV, trigger="test", n_sims=120, tournament_sims=50
    )

    assert summary["learning"]["evaluated_new"] == 1
    assert chain_pending(db_session) is False
    row = get_chain_status(db_session)
    assert row.last_success_at is not None
    assert row.covered_finished == 1
    assert row.last_trigger == "test"


def test_tracked_chain_failure_stays_pending_with_error(db_session, monkeypatch):
    """A chain that dies mid-run must NOT advance the success watermark — the
    finish stays owed for retry — and the failure is recorded for /api/health."""
    _seed(db_session)
    _finish(db_session, _first_group_match(db_session), 2, 1)

    def boom(db, mv, **kw):
        raise RuntimeError("OOM-killed mid-simulation")

    monkeypatch.setattr("pipeline.learning_loop.run_post_results_chain", boom)
    with pytest.raises(RuntimeError):
        run_tracked_post_results_chain(
            db_session, MV, trigger="test", n_sims=120, tournament_sims=50
        )

    assert chain_pending(db_session) is True
    row = get_chain_status(db_session)
    assert row.last_success_at is None
    assert row.last_attempt_at is not None
    assert "OOM-killed" in row.last_error


def test_evaluation_scores_exact_on_90_minute_basis(db_session):
    """FR-2.2: a tie decided by an extra-time goal must score exact-hits
    against the captured 90-minute score, while the winner verdict keeps the
    after-ET convention."""
    _seed(db_session)
    m = _first_group_match(db_session)
    pred = (
        db_session.query(Prediction)
        .filter_by(match_id=m.id, is_shadow=False)  # the row evaluation freezes
        .order_by(Prediction.id.desc())
        .first()
    )
    pred.predicted_score_home, pred.predicted_score_away = 1, 1
    _finish(db_session, m, 2, 1)  # after-ET final
    m.score_home_90, m.score_away_90 = 1, 1  # regulation score
    db_session.commit()

    evaluate_finished_predictions(db_session, MV)

    row = db_session.query(PredictionResult).filter_by(match_id=m.id, is_shadow=False).one()
    assert row.exact_score_correct is True  # 1-1 pick vs 1-1 at 90'
    assert row.outcome == "home"  # winner basis: final result


def test_post_results_chain_backfills_90min_before_evaluating(db_session):
    """Self-check fix: the whistle-time chain must run the goal-events
    backfill BEFORE evaluation — otherwise the append-only result row locks in
    the after-ET basis and the daily backfill can never heal it."""
    _seed(db_session)
    m = _first_group_match(db_session)
    m.stage = "R32"  # knockout: ET is possible, group-copy shortcut off
    pred = (
        db_session.query(Prediction)
        .filter_by(match_id=m.id, is_shadow=False)  # the row evaluation freezes
        .order_by(Prediction.id.desc())
        .first()
    )
    pred.predicted_score_home, pred.predicted_score_away = 1, 1
    _finish(db_session, m, 2, 1)  # after-ET final; 90' was 1-1
    m.goal_events = [
        {"minute": 10, "side": "home", "player": "A", "type": "goal"},
        {"minute": 80, "side": "away", "player": "B", "type": "goal"},
        {"minute": 100, "side": "home", "player": "C", "type": "goal"},
    ]
    db_session.commit()
    assert m.score_home_90 is None  # every live poll missed

    run_post_results_chain(db_session, MV)

    db_session.refresh(m)
    assert (m.score_home_90, m.score_away_90) == (1, 1)  # healed from events
    row = db_session.query(PredictionResult).filter_by(match_id=m.id, is_shadow=False).one()
    assert row.exact_score_correct is True  # evaluated on the healed basis


# --- residual ledger persistence + pre-tournament seeding (model v2 C1) -----


def test_update_tournament_state_persists_residual_ledger_when_form_channels_enabled(
    db_session, monkeypatch
):
    """With form_channels ON, the ledger is written same as before."""
    from ml.models.params import DEFAULT_PARAMS
    import pipeline.learning_loop as ll_mod

    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 2, 0)

    enabled = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(),
           "form_channels": {"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0}}
    )
    monkeypatch.setattr(ll_mod, "load_params", lambda: enabled)

    update_tournament_state(db_session)

    sh = db_session.query(TeamTournamentState).filter_by(team_id=m.team_home_id).one()
    assert sh.residual_ledger is not None
    assert len(sh.residual_ledger) == 1
    gf, ga = sh.residual_ledger[0]
    assert isinstance(gf, float) and isinstance(ga, float)


def test_ledger_zeroed_out_for_team_with_no_finished_matches(db_session):
    _seed(db_session)
    update_tournament_state(db_session)
    # No finished matches at all -> every team's ledger is empty/None, never
    # stale data from a previous run.
    rows = db_session.query(TeamTournamentState).all()
    for row in rows:
        assert not row.residual_ledger


def test_build_seed_ledgers_only_covers_requested_team_ids(db_session):
    """Guard cost: seeds are computed only for teams in the tournament, not
    every team with historical_matches."""
    load_structure(db_session)
    teams = db_session.query(Team).order_by(Team.id).limit(4).all()
    t1, t2, t3, t4 = teams
    now = datetime.now(timezone.utc)
    for i in range(3):
        db_session.add(HistoricalMatch(
            date=now - timedelta(days=(3 - i) * 30),
            team_a_id=t1.id, team_b_id=t2.id, score_a=2, score_b=0,
            competition="Friendly", is_neutral=True,
        ))
    for i in range(3):
        db_session.add(HistoricalMatch(
            date=now - timedelta(days=(3 - i) * 30),
            team_a_id=t3.id, team_b_id=t4.id, score_a=1, score_b=1,
            competition="Friendly", is_neutral=True,
        ))
    db_session.commit()

    seeds = build_seed_ledgers(db_session, {t1.id, t2.id})
    assert set(seeds.keys()) <= {t1.id, t2.id}
    assert t3.id not in seeds
    assert t4.id not in seeds


def test_build_seed_ledgers_caps_at_last_ten_matches(db_session):
    load_structure(db_session)
    teams = db_session.query(Team).order_by(Team.id).limit(2).all()
    t1, t2 = teams
    now = datetime.now(timezone.utc)
    for i in range(15):
        db_session.add(HistoricalMatch(
            date=now - timedelta(days=(15 - i) * 10),
            team_a_id=t1.id, team_b_id=t2.id, score_a=1, score_b=0,
            competition="Friendly", is_neutral=True,
        ))
    db_session.commit()

    seeds = build_seed_ledgers(db_session, {t1.id})
    assert len(seeds[t1.id]) == 10


def test_build_seed_ledgers_oldest_first_ordering(db_session):
    load_structure(db_session)
    teams = db_session.query(Team).order_by(Team.id).limit(2).all()
    t1, t2 = teams
    now = datetime.now(timezone.utc)
    # Distinct scorelines so we can tell ordering apart: oldest scores 0, most
    # recent scores 5.
    for i in range(3):
        db_session.add(HistoricalMatch(
            date=now - timedelta(days=(3 - i) * 10),
            team_a_id=t1.id, team_b_id=t2.id, score_a=i, score_b=0,
            competition="Friendly", is_neutral=True,
        ))
    db_session.commit()

    seeds = build_seed_ledgers(db_session, {t1.id})
    ledger = seeds[t1.id]
    assert len(ledger) == 3
    # gf residual should be monotonically increasing across the ledger since
    # score_a increases 0, 1, 2 while expectation stays roughly flat.
    assert ledger[0][0] < ledger[1][0] < ledger[2][0]


def test_update_tournament_state_seeds_ledger_when_form_channels_enabled(db_session, monkeypatch):
    from ml.models.params import DEFAULT_PARAMS
    import pipeline.learning_loop as ll_mod

    _seed(db_session)
    m = _first_group_match(db_session)

    # Give the home team pre-tournament history to seed from.
    now = datetime.now(timezone.utc)
    other = db_session.query(Team).filter(Team.id != m.team_home_id).first()
    db_session.add(HistoricalMatch(
        date=now - timedelta(days=60),
        team_a_id=m.team_home_id, team_b_id=other.id, score_a=3, score_b=0,
        competition="Friendly", is_neutral=True,
    ))
    db_session.commit()
    _finish(db_session, m, 2, 0)

    enabled = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(),
           "form_channels": {"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0}}
    )
    monkeypatch.setattr(ll_mod, "load_params", lambda: enabled)

    update_tournament_state(db_session)

    sh = db_session.query(TeamTournamentState).filter_by(team_id=m.team_home_id).one()
    # Seeded ledger has the pre-tournament match PLUS the tournament match.
    assert len(sh.residual_ledger) == 2


def test_update_tournament_state_no_seed_when_form_channels_disabled(db_session):
    # form_channels is None by default -- no seeding cost/behavior change, and
    # (deploy-window hardening) the ledger column itself is never written.
    _seed(db_session)
    m = _first_group_match(db_session)
    now = datetime.now(timezone.utc)
    other = db_session.query(Team).filter(Team.id != m.team_home_id).first()
    db_session.add(HistoricalMatch(
        date=now - timedelta(days=60),
        team_a_id=m.team_home_id, team_b_id=other.id, score_a=3, score_b=0,
        competition="Friendly", is_neutral=True,
    ))
    db_session.commit()
    _finish(db_session, m, 2, 0)

    update_tournament_state(db_session)

    sh = db_session.query(TeamTournamentState).filter_by(team_id=m.team_home_id).one()
    # form_channels dark -- the column is never touched, not even zeroed.
    assert sh.residual_ledger is None


# --- no-double-count guard: legacy scalar OFF when form_channels active -----


def test_effective_elos_excludes_legacy_form_scalar_when_form_channels_enabled(db_session, monkeypatch):
    from ml.models.params import DEFAULT_PARAMS
    import pipeline.learning_loop as ll_mod

    _seed(db_session)
    m = _first_group_match(db_session)
    _finish(db_session, m, 3, 0)  # a decisive result -> non-zero form_adjustment
    update_tournament_state(db_session)

    row = db_session.query(TeamTournamentState).filter_by(team_id=m.team_home_id).one()
    assert row.form_adjustment != 0.0  # sanity: the legacy scalar is non-trivial

    off_elos = effective_elos(db_session)

    enabled = DEFAULT_PARAMS.__class__(
        **{**DEFAULT_PARAMS.to_dict(),
           "form_channels": {"c_atk": 0.25, "c_def": 0.25, "cap": 0.15, "half_life": 3.0}}
    )
    monkeypatch.setattr(ll_mod, "load_params", lambda: enabled)
    on_elos = effective_elos(db_session)

    # With form_channels active, the legacy scalar must NOT be added -- the
    # effective elo for this team drops back toward base+elo_delta only.
    assert on_elos[m.team_home_id] != off_elos[m.team_home_id]
    base_plus_delta = off_elos[m.team_home_id] - row.form_adjustment
    assert on_elos[m.team_home_id] == pytest.approx(base_plus_delta)


# --- deploy-window hardening: residual_ledger dark-mode never touched -------
#
# Render auto-deploys code before refresh.yml applies migrations. If the
# residual_ledger column is read or written by a request-time path while
# form_channels is dark (the shipped default), a not-yet-migrated prod DB
# would 500 on every full-entity query -- and /api/internal/refresh-live hits
# update_tournament_state -> effective_elos every ~5 min mid-tournament. Two
# guards: the column is ORM-deferred (excluded from SELECT * unless
# explicitly accessed -- see app/models/__init__.py) and update_tournament_state
# only ever assigns to it when form_channels is enabled.


def test_update_tournament_state_never_sets_residual_ledger_when_form_channels_dark(
    db_session,
):
    """form_channels=None (the shipped state): update_tournament_state must
    never assign row.residual_ledger at all -- not even to []. A freshly
    created row's attribute stays at the SQLAlchemy default (None/unset), and
    a PRE-EXISTING row's prior value is left completely alone."""
    _seed(db_session)
    m = _first_group_match(db_session)

    # Pre-existing row with a stale ledger from a prior form_channels-enabled
    # run -- the write-side gate must leave it untouched, not zero it.
    stale_row = TeamTournamentState(
        team_id=m.team_home_id, residual_ledger=[[9.9, -9.9]]
    )
    db_session.add(stale_row)
    db_session.commit()

    _finish(db_session, m, 2, 0)
    update_tournament_state(db_session)

    sh = db_session.query(TeamTournamentState).filter_by(team_id=m.team_home_id).one()
    assert sh.residual_ledger == [[9.9, -9.9]]  # untouched, stale value preserved

    # A brand-new row (away team had no prior TeamTournamentState) must also
    # never get its residual_ledger set while dark.
    sa = db_session.query(TeamTournamentState).filter_by(team_id=m.team_away_id).one()
    assert sa.residual_ledger is None


def test_effective_elos_select_never_references_residual_ledger_column(db_session):
    """Compile the exact query effective_elos issues
    (db.query(TeamTournamentState).all()) and inspect the generated SQL: the
    residual_ledger column must not appear, proving the deferred mapping
    actually protects this request-time path against an unmigrated DB."""
    from sqlalchemy import inspect as sa_inspect

    _seed(db_session)
    q = db_session.query(TeamTournamentState)
    compiled = str(q.statement.compile(db_session.get_bind()))
    assert "residual_ledger" not in compiled

    # Sanity: the column is genuinely mapped as deferred, not just absent from
    # this particular query by coincidence.
    mapper = sa_inspect(TeamTournamentState)
    prop = mapper.attrs["residual_ledger"]
    assert prop.deferred is True

    # effective_elos itself must not 500 or touch the column under a
    # form_channels=None load (the request-time path this guards).
    result = effective_elos(db_session)
    assert isinstance(result, dict) and result
