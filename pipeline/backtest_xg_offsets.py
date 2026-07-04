"""A/B/C WC backtest — a SANITY CHECK, not the proof bar (Phase 7, xG pivot).

Compares three variants on held-out past World Cup editions, walk-forward
(each edition's fitters train ONLY on rows strictly before that edition's
first match, via fit_offsets' own exclusive ref_date cutoff):

    A. no offsets            — the served v0.1 engine as-is
    B. goals-offsets         — fit_offsets on score_home/score_away (today's
                                shadow, if it were promoted)
    C. xG-nudged offsets     — the re-anchor + kappa-blend from
                                pipeline/build_xg_offsets, applied per-edition

All three reuse the SAME fit_offsets ML core (pipeline/fit_attack_defence.py)
and the SAME re-anchor/blend (pipeline/build_xg_offsets.py) — nothing here
re-derives MLE, decay, shrink, cap, or re-anchor math.

Framing: StatsBomb xG only exists in recent editions' training windows (~2
clusters — Euro/Copa/AFCON 2023-24 plus WC22 itself), too few matches to
accept or reject the xG nudge on significance. This report exists so a null
result reads as "underpowered here, not disproven" — it prints per-edition xG
coverage alongside the metrics for exactly that reason. The served model
(params.team_offsets stays null) is unaffected regardless of what this prints.

Runs OFFLINE only, over enriched rows already in memory (pipeline.backtest_data
.build_enriched_rows(db) rows, with xg_a/xg_b attached the same way
build_xg_offsets attaches them). Nothing here writes to a store or a DB.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from ml.evaluation.backtest import compute_metrics, is_world_cup_final_match, model_probs
from ml.models.baseline_logistic import result_label
from ml.models.poisson import expected_goals_from_elo, predict_from_lambdas
from ml.models.team_offsets import offsets_for
from pipeline.build_xg_offsets import blend_offsets, reanchor
from pipeline.fit_attack_defence import fit_offsets

log = logging.getLogger(__name__)

#: Default editions this sanity check walks forward over. Callers may pass a
#: narrower list (e.g. a smoke test's single synthetic year).
DEFAULT_EDITIONS: list[int] = [2018, 2022]


def _offsets_probs(rows: list[dict], target: list[dict], offsets_by_id: dict[int, dict]) -> list:
    """Predict W/D/L probs for `target` rows using per-team offsets keyed by
    team id (already shrunk/capped by fit_offsets/blend_offsets). Falls back to
    (0, 0) for any team missing from the store — same as offsets_for's unknown-
    team default, but keyed by id here since these rows never carry names."""
    out = []
    for r in target:
        atk_h, def_h = _lookup(offsets_by_id, r["home_id"])
        atk_a, def_a = _lookup(offsets_by_id, r["away_id"])
        adv = 0.0 if r["is_neutral"] else 0.0  # home_adv folded into pre_home/pre_away already
        lam_h, lam_a = expected_goals_from_elo(
            r["pre_home"], r["pre_away"], adv,
            atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
        )
        pred = predict_from_lambdas(lam_h, lam_a)
        out.append((pred.prob_home_win, pred.prob_draw, pred.prob_away_win))
    return out


def _lookup(offsets_by_id: dict[int, dict], team_id: int) -> tuple[float, float]:
    entry = offsets_by_id.get(team_id)
    if entry is None:
        return 0.0, 0.0
    return entry["atk"], entry["def"]


def _fit_xg_nudged(rows: list[dict], train: list[dict], ref) -> dict[int, dict]:
    """Fit goals offsets + xG offsets on `train` (mirrors build_xg_offsets, but
    over in-memory rows instead of a DB), re-anchor, and blend. Returns the SAME
    {team_id: {atk, def, n_matches}} shape fit_offsets returns (extended with
    the blend, not the fitter's own n_eff key — callers only need atk/def)."""
    goals_offsets = fit_offsets(train, ref)
    xg_rows = [r for r in train if r.get("xg_a") is not None and r.get("xg_b") is not None]
    xg_offsets: dict[int, dict] = {}
    if xg_rows:
        xg_offsets = fit_offsets(xg_rows, ref, goal_keys=("xg_a", "xg_b"))
    delta = reanchor(goals_offsets, xg_offsets)
    if not xg_offsets:
        return goals_offsets
    return blend_offsets(goals_offsets, xg_offsets, delta)


def backtest_one_edition(rows: list[dict], year: int) -> dict:
    """Walk-forward A/B/C comparison for one held-out WC edition, plus its xG
    coverage (matches in the edition with both sides' xG present vs total)."""
    target = [
        r for r in rows if is_world_cup_final_match(r["competition"]) and r["date"].year == year
    ]
    if not target:
        raise ValueError(f"no World Cup matches found for {year}")
    first_date = min(r["date"] for r in target)
    train = [r for r in rows if r["date"] < first_date]
    # fit_offsets' own ref_date cutoff is exclusive; step one day past the
    # edition's first match date is unnecessary here since train already
    # excludes >= first_date rows — ref_date == first_date keeps the cutoff
    # identical to the split above (no leakage, no accidental inclusion).
    ref = first_date

    labels = [result_label(r["score_home"], r["score_away"]) for r in target]

    # A: no offsets — the served v0.1 engine, unchanged.
    a_probs = [model_probs(r["pre_home"], r["pre_away"], r["is_neutral"]) for r in target]

    # B: goals-offsets — fit_offsets on score_home/score_away only.
    goals_offsets = fit_offsets(train, ref)
    b_probs = _offsets_probs(rows, target, goals_offsets)

    # C: xG-nudged offsets — re-anchor + kappa-blend on top of the goals fit.
    xg_offsets = _fit_xg_nudged(rows, train, ref)
    c_probs = _offsets_probs(rows, target, xg_offsets)

    xg_covered = sum(
        1 for r in target if r.get("xg_a") is not None and r.get("xg_b") is not None
    )

    return {
        "year": year,
        "n_matches": len(target),
        "a_no_offsets": compute_metrics(a_probs, labels),
        "b_goals_offsets": compute_metrics(b_probs, labels),
        "c_xg_offsets": compute_metrics(c_probs, labels),
        "xg_coverage": {"matches": len(target), "xg_covered": xg_covered},
    }


def run_abc_backtest(rows: list[dict], editions: list[int] = DEFAULT_EDITIONS) -> dict:
    """Run the A/B/C sanity comparison over each edition in `editions` and
    print a one-line-per-variant report plus per-edition xG coverage. Never
    raises on a null/underpowered xG signal — an edition with zero xG-covered
    training rows just falls through to the goals-only blend (build_xg_offsets'
    own kill-switch), so C degenerates to B rather than crashing."""
    editions_out = []
    for year in editions:
        edition = backtest_one_edition(rows, year)
        editions_out.append(edition)

        cov = edition["xg_coverage"]
        print(f"\n=== World Cup {year} ({edition['n_matches']} matches) ===")
        print(
            f"  xG coverage: {cov['xg_covered']}/{cov['matches']} target matches "
            "(train-side coverage varies by edition; see per-run summary)"
        )
        for key, label in (
            ("a_no_offsets", "A no-offsets"),
            ("b_goals_offsets", "B goals-offsets"),
            ("c_xg_offsets", "C xG-nudged"),
        ):
            m = edition[key]
            print(
                f"  {label:<18} log_loss={m['log_loss']:.4f} brier={m['brier']:.4f} "
                f"acc={m['accuracy']:.3f}"
            )

    print(
        "\nNote: this is a sanity check, NOT the proof bar. StatsBomb xG exists "
        "only in recent editions' training windows (~2 clusters) — too few "
        "matches to accept or reject the xG nudge on significance. A null here "
        "reads as underpowered, not as evidence xG doesn't help. The served "
        "model (params.team_offsets) is unaffected regardless."
    )
    return {"editions": editions_out}


def main() -> int:
    from app.db import SessionLocal
    from pipeline.backtest_data import build_enriched_rows

    db = SessionLocal()
    try:
        from app.models import HistoricalMatch

        rows = build_enriched_rows(db)
        ordered = (
            db.query(HistoricalMatch)
            .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
            .all()
        )
        for row, orm in zip(rows, ordered):
            row["xg_a"] = orm.xg_a
            row["xg_b"] = orm.xg_b
    finally:
        db.close()

    run_abc_backtest(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
