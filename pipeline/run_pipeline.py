"""Daily pipeline orchestrator (PRD §7, task 7).

Runs the full refresh: load WC2026 structure -> ingest historical results ->
recompute Elo -> compute team stats -> (optional FIFA rankings) -> generate
predictions + standings. Every step is idempotent and logged; any failure is
logged loudly and re-raised so the scheduler (GitHub Actions) marks the run failed.

Usage:
    PYTHONPATH=backend:. python -m pipeline.run_pipeline
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy.orm import Session

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [pipeline] %(message)s"
)
log = logging.getLogger(__name__)


def _run_league_pipeline(db: Session, step, n_sims: int) -> None:
    """League pivot D5/D7 (docs/LEAGUE-PIVOT-PLAN.md) + League Score
    Predictions design doc (2026-07-24, "Pipeline" section): the football-
    league path, taken instead of the WC26 steps below when settings.
    pipeline_target == "league". Iterates pipeline.leagues.ACTIVE_LEAGUES
    (Phase 1: exactly ["epl"]) -- per configured league: structure upsert ->
    sync its finished results into history (from the same fetch_fixtures
    payload the structure step already pulled). Then, once across every
    league just ingested (these steps have no tournament filter to begin
    with -- see compute_club_elo.py's CLUB_COMPETITION-wide replay and
    learning_loop.py's _finished_matches): club Elo update, per-league
    predictions tagged the club model version, learning-loop scoring, and
    the score-prediction grading pass (human tips, not the model's own
    record -- pipeline/league_score_predictions.py). No WC-only step (wc26
    structure, KO venues, bracket sim) is ever called here — they simply
    aren't part of this branch, which is what "skip cleanly" means for a
    league run.

    Step naming: with exactly one configured league (Phase 1, and every
    existing test) the per-league step names stay unprefixed -- byte-for-
    byte the same summary shape ("league_structure"/"league_results_sync"/
    "predictions") this branch has always produced. Only once more than one
    league actually resolves (Phase 2) do those three steps gain a "{code}_"
    prefix, so two leagues' summaries never collide under the same key.
    club_elo/learning_loop/score_predictions_grading stay unprefixed
    regardless of league count -- they were never tournament-scoped in the
    step-naming sense (club_elo's REPLAY is now looped per league below --
    see its own comment -- but the summary still reports under one key).

    Per-league ingest isolation (League Score Predictions Phase 2): once more
    than one league is configured, one league's structure/results-sync
    failure is logged and that league is skipped, but the rest still run --
    a bad API-Football response for one league must not take the others down
    with it. With exactly one league configured (Phase 1, and every
    pre-Phase-2 test) this is a no-op: a solo failure still propagates and
    fails the whole run, exactly as it always has.
    """
    from app.models import Tournament
    from pipeline.compute_club_elo import compute_and_store_club_elo
    from pipeline.generate_predictions import generate_predictions
    from pipeline.ingest.club_results import sync_finished_matches_to_history
    from pipeline.ingest.league_structure import load_league_structure
    from pipeline.leagues import ACTIVE_LEAGUES, LEAGUES
    from pipeline.learning_loop import run_learning_loop

    configured: list[tuple[str, dict]] = []
    for code in ACTIVE_LEAGUES:
        cfg = LEAGUES.get(code)
        if cfg is None:
            log.warning(
                "league pipeline: %r is in ACTIVE_LEAGUES but has no "
                "pipeline.leagues.LEAGUES registry entry -- skipping", code,
            )
            continue
        configured.append((code, cfg))

    if not configured:
        log.warning("league pipeline: no configured league resolved to a runnable config -- nothing to do")
        return

    def _prefix(code: str) -> str:
        return "" if len(configured) == 1 else f"{code}_"

    isolate_failures = len(configured) > 1
    leagues_run: list[tuple[str, Tournament]] = []
    for code, cfg in configured:
        try:
            league_summary = step(
                f"{_prefix(code)}league_structure",
                lambda cfg=cfg: load_league_structure(
                    db, teams_file=cfg["teams_file"], tournament_name=cfg["tournament_name"],
                    group_name=cfg["group_name"], league_id=cfg["league_id"], season=cfg["season"],
                ),
            )
            tournament = db.get(Tournament, league_summary["tournament_id"])
            step(
                f"{_prefix(code)}league_results_sync",
                lambda t=tournament, cfg=cfg: sync_finished_matches_to_history(
                    db, t, competition=cfg["club_competition"],
                ),
            )
        except Exception:  # noqa: BLE001 - isolation boundary, see docstring
            if not isolate_failures:
                raise
            log.exception(
                "league pipeline: %s ingest FAILED -- skipping this league, "
                "continuing with the rest", code,
            )
            db.rollback()  # discard this league's partial (uncommitted) flush
            continue
        leagues_run.append((code, tournament))

    # Per-league club Elo replay (recon item 3: with >1 league sharing
    # historical_matches, a single shared-string replay would blend leagues'
    # rows together and could only ever persist ONE tournament's
    # home_advantage_value). Iterates every CONFIGURED league (not just
    # leagues_run) -- club Elo replays historical_matches rows, a data source
    # independent of this run's live fixture ingest, so it still runs even
    # for a league whose structure step failed above (compute_and_store_club_elo
    # tolerates a not-yet-created Tournament row). Summary stays under the
    # single "club_elo" key regardless of league count; with exactly one
    # league configured, its value is that league's own flat summary dict,
    # byte-for-byte the shape every existing test already asserts against.
    def _club_elo_all_leagues() -> dict:
        results = {
            code: compute_and_store_club_elo(
                db, competition=cfg["club_competition"], tournament_name=cfg["tournament_name"],
            )
            for code, cfg in configured
        }
        return results[configured[0][0]] if len(configured) == 1 else results

    step("club_elo", _club_elo_all_leagues)

    for code, tournament in leagues_run:
        step(
            f"{_prefix(code)}predictions",
            lambda t=tournament: generate_predictions(
                db, model_version="poisson-elo-club-v0.1",
                n_sims=n_sims, tournament_id=t.id,
            ),
        )

    # Also not tournament-scoped (learning_loop._finished_matches has no
    # tournament filter) -- one call evaluates every league's finished
    # matches against the model's own frozen predictions.
    step("learning_loop", lambda: run_learning_loop(db, "poisson-elo-club-v0.1"))

    # New: score-prediction grading pass (League Score Predictions design
    # doc) -- grades HUMAN picks, a separate table/module from the model's
    # own learning_loop record above. Best-effort, mirroring the WC26
    # branch's _prob_snapshots below: a failure here must never block the
    # model pipeline that already landed and committed above it.
    def _score_predictions_grading() -> dict:
        from pipeline.league_score_predictions import grade

        try:
            return {"graded": grade(db)}
        except Exception:  # noqa: BLE001 - best-effort, log loudly and continue
            log.exception("score_predictions_grading FAILED (best-effort, continuing)")
            return {"graded": 0, "error": True}

    step("score_predictions_grading", _score_predictions_grading)
    log.info("league pipeline complete")


def run_pipeline(db: Session, results_df=None, n_sims: int = 5000) -> dict:
    """Execute the full refresh. Pass results_df to skip the network download
    (used by tests). Returns a summary of every step."""
    from app.chain_status import finished_match_count, record_success
    from app.config import settings
    from app.model_meta import current_model_version
    from app.scoring import recompute_scores, knockout_results_from_db
    from pipeline.compute_elo import compute_and_store_elo
    from pipeline.generate_predictions import generate_predictions
    from pipeline.ingest.fifa_rankings import LOCAL_RANKINGS_CSV, apply_rankings, load_rankings_df
    from pipeline.ingest.historical_results import download_results_df, load_historical
    from pipeline.ingest.ko_venues import apply_ko_venues
    from pipeline.ingest.wc26_structure import load_structure
    from pipeline.learning_loop import run_learning_loop
    from pipeline.prune_auth import prune_auth_rows
    from pipeline.team_stats import compute_team_stats

    summary: dict = {}

    def step(name: str, fn):
        log.info("step: %s …", name)
        try:
            result = fn()
        except Exception:  # noqa: BLE001 - log + re-raise so the scheduler fails
            log.exception("step FAILED: %s", name)
            raise
        log.info("step done: %s -> %s", name, result)
        summary[name] = result
        return result

    # League pivot D7: config stays single-competition. When pointed at a
    # league this branch replaces the entire WC26 sequence below (never a
    # partial mix of the two) — the WC path underneath is untouched code,
    # so it stays byte-identical whenever pipeline_target is left at "wc26".
    if settings.pipeline_target == "league":
        _run_league_pipeline(db, step, n_sims)
        return summary

    step("structure", lambda: load_structure(db))
    # KO venues are static (keyed by match_no) — load_structure fills group-stage
    # venues, this fills knockout ones. Idempotent, so safe on every run.
    step("ko_venues", lambda: apply_ko_venues(db))
    df = results_df if results_df is not None else step("download_results", download_results_df)
    step("historical", lambda: load_historical(db, df))
    step("elo", lambda: compute_and_store_elo(db))
    step("team_stats", lambda: compute_team_stats(db))

    # FIFA rankings are optional (Elo is primary). Skip cleanly if no source.
    if LOCAL_RANKINGS_CSV.exists():
        step("fifa_rankings", lambda: apply_rankings(db, load_rankings_df()))
    else:
        log.info("step skipped: fifa_rankings (no %s)", LOCAL_RANKINGS_CSV.name)

    # Pre-kickoff odds snapshot (FR-4.1) BEFORE predictions, so the shadow
    # twins generated below can anchor to a fresh market total. Best-effort by
    # contract (refresh_odds never raises, FR-4.2); skipped without a key.
    if settings.api_football_api_key:
        from pipeline.ingest.injuries import refresh_injuries
        from pipeline.ingest.odds import backfill_finished_odds, refresh_odds

        step("odds", lambda: refresh_odds(db, settings.api_football_api_key))
        # Outage recovery: a match whose pre-kickoff window fell inside a
        # scheduler outage still gets its frozen pre-match consensus while
        # api-sports retains it (~7 days post-match). No-op when nothing owed.
        step("odds_backfill",
             lambda: backfill_finished_odds(db, settings.api_football_api_key))
        # Day-ahead availability snapshot, BEFORE predictions so the twin can use it.
        step("injuries", lambda: refresh_injuries(db, settings.api_football_api_key))
    else:
        log.info("step skipped: odds + injuries (no API_FOOTBALL_API_KEY)")

    # Learning loop AFTER the Elo base is fresh, BEFORE predictions consume the
    # adjusted ratings: evaluate finished matches, refresh tournament state.
    # Count first: a match finishing mid-pipeline stays owed for the next sweep.
    covered = finished_match_count(db)
    # 90' basis before evaluation: fill regulation scores history/cron-gaps
    # missed, so exact-score results land on the basis the model predicts.
    from pipeline.backfill_90min import backfill_90min_scores

    step("backfill_90min", lambda: backfill_90min_scores(db))
    step("learning_loop", lambda: run_learning_loop(db, current_model_version()))
    step("predictions", lambda: generate_predictions(db, n_sims=n_sims))

    # Movers-feature snapshot: best-effort, like odds/injuries above (never
    # raises) -- a failure here must not block prediction_coverage,
    # bracket_scores, or the chain_status heartbeat that follow.
    def _prob_snapshots() -> dict:
        from pipeline.prob_snapshots import snapshot_football

        try:
            return {"written": snapshot_football(db)}
        except Exception:  # noqa: BLE001 - best-effort, log loudly and continue
            log.exception("prob_snapshots FAILED (best-effort, continuing)")
            return {"written": 0, "error": True}

    step("prob_snapshots", _prob_snapshots)

    # Coverage assertion (FR-1.2): after the predictions step, no imminent
    # match may lack a frozen prediction. Loud in the summary, not fatal —
    # the sweep in the live path is the healer, this is the detector.
    def _prediction_coverage() -> dict:
        from app.prediction_coverage import matches_missing_prediction

        due = matches_missing_prediction(db, within_hours=48)
        if due:
            log.error(
                "prediction coverage gap: %d match(es) without a frozen "
                "prediction: %s", len(due), [m.id for m in due],
            )
        return {"missing": len(due), "match_ids": [m.id for m in due]}

    step("prediction_coverage", _prediction_coverage)
    step("bracket_scores", lambda: recompute_scores(db, knockout_results=knockout_results_from_db(db)))
    # The steps above are the post-results chain at full depth — stamp the
    # heartbeat so /api/health and the opportunistic retries know nothing is owed.
    step("chain_status", lambda: record_success(db, covered, trigger="pipeline"))
    step("prune_auth", lambda: prune_auth_rows(db))
    log.info("pipeline complete")
    return summary


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.db import Base
    import app.models  # noqa: F401

    engine = create_engine(settings.sqlalchemy_url, future=True)
    Base.metadata.create_all(engine)  # safety for fresh DBs; Alembic owns prod schema
    db = sessionmaker(bind=engine, future=True)()
    try:
        run_pipeline(db)
    except Exception:  # noqa: BLE001
        log.error("pipeline run failed")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
