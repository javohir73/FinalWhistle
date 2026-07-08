"""WC26 group-stage leak-free replay (model v2 design doc §5).

Re-predicts the finished WC26 group matches using ONLY information available
pre-kickoff of each match. Effective ratings are rebuilt from the historical
Elo base + a `ml.ratings.tournament.replay_tournament` pass over the PREFIX of
matches strictly before that kickoff (mirroring how
`pipeline.learning_loop.update_tournament_state` builds `TournamentMatch` rows,
including the host `home_adv` bonus) — never the final post-tournament state,
which would leak future results into an earlier prediction.

Each row also carries a residual ledger continuing across the pre-tournament ->
tournament boundary (the C1 fix in the design doc): the team's pre-tournament
tail (`pipeline.backtest_data.build_enriched_rows`, capped) followed by its
in-tournament residuals so far, each measured the same way — actual goals
minus the model's own pre-match expectation.

Read-only: this module never writes to the database. Score any variant (same
{name, params, form_channels, calibrator} shape as ml.evaluation.experiments)
on the 71 matches and compare against the stored production ledger
(prediction_results), recomputed here rather than hardcoded.

Usage:
    PYTHONPATH=backend:. python -m pipeline.replay_wc26
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Match, PredictionResult, Team
from ml.evaluation.experiments import build_variant, score_variant
from ml.features.build_features import estimate_strength
from ml.models.params import ModelParams, load_params
from ml.models.poisson import expected_goals_from_elo
from ml.ratings.elo import HOME_ADVANTAGE
from ml.ratings.tournament import TournamentMatch, replay_tournament
from pipeline.backtest_data import LEDGER_CAP, build_enriched_rows

log = logging.getLogger(__name__)

_PRODUCTION_MODEL_VERSION = "poisson-elo-v0.2"


def _finished_group_matches(db: Session) -> list[Match]:
    return (
        db.query(Match)
        .filter(Match.status == "finished", Match.stage == "group")
        .order_by(Match.kickoff_utc.asc(), Match.id.asc())
        .all()
    )


def _pretournament_ledger_tails(
    db: Session, served: ModelParams
) -> dict[int, list[tuple[float, float]]]:
    """Each team's residual ledger as of the moment the tournament starts —
    the C1 boundary-continuity fix: pre-tournament form carries in instead of
    resetting to zero. Reuses build_enriched_rows' own ledger construction
    (LEDGER_CAP, now defaulting to the SERVED goals scale itself) so the
    convention matches deliverable 1 exactly: walk the enriched rows
    oldest-first and keep each team's latest ledger snapshot PLUS its own
    match residual appended — the last time a team appears is its full
    pre-tournament tail. The "own match residual" computed here uses the SAME
    ``served`` base/beta (not the v0.1 constants) so every residual in the
    ledger — pre-tournament and in-tournament alike — is measured on one
    consistent scale (model v2 review finding: ablation validity)."""
    rows = build_enriched_rows(db, base=served.base, beta=served.beta)
    tails: dict[int, list[tuple[float, float]]] = {}
    for row in rows:
        home_id, away_id = row["home_id"], row["away_id"]
        adv = 0.0 if row["is_neutral"] else HOME_ADVANTAGE
        lam_home, lam_away = expected_goals_from_elo(
            row["pre_home"], row["pre_away"], adv, base=served.base, beta=served.beta,
        )
        gf_home, ga_home = row["score_home"] - lam_home, row["score_away"] - lam_away
        tails[home_id] = (tails.get(home_id, []) + [(gf_home, ga_home)])[-LEDGER_CAP:]
        tails[away_id] = (tails.get(away_id, []) + [(-ga_home, -gf_home)])[-LEDGER_CAP:]
    return tails


def build_wc26_rows(db: Session) -> list[dict]:
    """Leak-free rows for the 71 finished WC26 group matches.

    Row shape matches ml.evaluation.experiments' expectations: pre_home,
    pre_away (effective ratings, replay_tournament prefix only), is_neutral,
    score_home, score_away, date, competition, ledger_home, ledger_away.
    """
    finished = _finished_group_matches(db)
    if not finished:
        return []

    served = load_params()
    teams = db.query(Team).all()
    base_elos = {t.id: estimate_strength(t)[0] for t in teams}

    # Running per-team ledger: starts at the pre-tournament tail and grows one
    # entry per match AFTER that match's row has been built (never before).
    running_ledgers: dict[int, list[tuple[float, float]]] = {
        tid: list(entries)
        for tid, entries in _pretournament_ledger_tails(db, served).items()
    }

    rows: list[dict] = []
    for i, m in enumerate(finished):
        prefix = finished[:i]  # strictly prior matches only — the leak guard
        tmatches = [
            TournamentMatch(
                home_id=p.team_home_id, away_id=p.team_away_id,
                score_home=p.score_home, score_away=p.score_away,
                stage=p.stage or "group",
                home_adv=HOME_ADVANTAGE if p.host_team_id == p.team_home_id else 0.0,
            )
            for p in prefix
        ]
        states = replay_tournament(
            base_elos, tmatches, goals_base=served.base, goals_beta=served.beta,
        )
        home_delta = states[m.team_home_id].elo_delta if m.team_home_id in states else 0.0
        away_delta = states[m.team_away_id].elo_delta if m.team_away_id in states else 0.0
        eff_home = base_elos[m.team_home_id] + home_delta
        eff_away = base_elos[m.team_away_id] + away_delta

        is_neutral = m.host_team_id not in (m.team_home_id, m.team_away_id)
        adv = 0.0 if is_neutral else HOME_ADVANTAGE

        rows.append({
            "home_id": m.team_home_id,
            "away_id": m.team_away_id,
            "pre_home": eff_home,
            "pre_away": eff_away,
            "is_neutral": is_neutral,
            "score_home": m.score_home,
            "score_away": m.score_away,
            "date": m.kickoff_utc,
            "competition": "FIFA World Cup",
            "ledger_home": list(running_ledgers.get(m.team_home_id, []))[-LEDGER_CAP:],
            "ledger_away": list(running_ledgers.get(m.team_away_id, []))[-LEDGER_CAP:],
        })

        # Append THIS match's own residual for LATER rows only — the row just
        # built above already had its ledger snapshotted, so it can never see
        # its own result. Served scale (not v0.1 constants), matching every
        # other residual in this ledger (model v2 review finding).
        lam_home, lam_away = expected_goals_from_elo(
            eff_home, eff_away, adv, base=served.base, beta=served.beta,
        )
        gf_home, ga_home = m.score_home - lam_home, m.score_away - lam_away
        running_ledgers[m.team_home_id] = (running_ledgers.get(m.team_home_id, []) + [(gf_home, ga_home)])[-LEDGER_CAP:]
        running_ledgers[m.team_away_id] = (running_ledgers.get(m.team_away_id, []) + [(-ga_home, -gf_home)])[-LEDGER_CAP:]

    return rows


def _production_reference(db: Session) -> dict:
    """Recompute the stored production ledger's metrics from
    prediction_results (never hardcoded) for side-by-side comparison."""
    results = (
        db.query(PredictionResult)
        .join(Match, PredictionResult.match_id == Match.id)
        .filter(
            PredictionResult.is_shadow.is_(False),
            PredictionResult.model_version == _PRODUCTION_MODEL_VERSION,
            Match.status == "finished",
            Match.stage == "group",
        )
        .all()
    )
    n = len(results)
    if n == 0:
        return {"n": 0, "accuracy": float("nan"), "brier": float("nan"), "log_loss": float("nan")}
    accuracy = sum(1 for r in results if r.winner_correct) / n
    brier = sum(r.brier for r in results) / n
    log_loss = sum(r.log_loss for r in results) / n
    return {"n": n, "accuracy": accuracy, "brier": brier, "log_loss": log_loss}


def replay_wc26(db: Session, variant_names: list[str] | None = None, val_days: int = 730) -> dict:
    """Score variants on the 71 finished WC26 group matches, leak-free.

    The validation window for tuning/calibration is the 730 days before the
    tournament's first kickoff, taken from build_enriched_rows' pre-tournament
    history (same convention as ml.evaluation.backtest.walk_forward) — the
    tournament itself is held out throughout, exactly like the WC2018/WC2022
    backtests.
    """
    rows = build_wc26_rows(db)
    if not rows:
        raise ValueError("no finished WC26 group matches found")

    from ml.evaluation.tune import validation_window

    history = build_enriched_rows(db)
    first_kickoff = min(r["date"] for r in rows)
    val = validation_window(history, first_kickoff, days=val_days)

    if variant_names is None:
        from ml.evaluation.experiments import _CORE_VARIANTS, _OPTIONAL_VARIANTS, form_module_available
        variant_names = list(_CORE_VARIANTS)
        for opt in _OPTIONAL_VARIANTS:
            if "form" not in opt or form_module_available():
                variant_names.append(opt)

    variants_out: dict[str, dict] = {}
    for name in variant_names:
        try:
            variant = build_variant(name, val)
        except ImportError:
            continue
        variants_out[name] = score_variant(rows, variant, val_rows=val)

    return {
        "n_matches": len(rows),
        "variants": variants_out,
        "production_reference": _production_reference(db),
    }


def format_reference(ref: dict) -> str:
    return (
        f"  {'production ledger':<16} log_loss={ref['log_loss']:.4f} "
        f"brier={ref['brier']:.4f} acc={ref['accuracy']:.3f} n={ref['n']}"
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        result = replay_wc26(db)
    finally:
        db.close()

    log.info("WC26 group stage replay (%d matches, leak-free)\n", result["n_matches"])
    for name, m in result["variants"].items():
        log.info(
            "  %-16s log_loss=%.4f brier=%.4f acc=%.3f ece=%.4f n=%d",
            name, m["log_loss"], m["brier"], m["accuracy"], m["ece"], m["n"],
        )
    log.info("\nStored production ledger (poisson-elo-v0.2, for reference):")
    log.info(format_reference(result["production_reference"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
