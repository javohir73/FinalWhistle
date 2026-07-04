"""Offline time-decayed Poisson MLE of per-team attack/defence offsets (FR-5.1).

The served engine maps one Elo diff symmetrically into both lambdas, so it
cannot represent "low-scoring team" or "leaky defence". This fitter learns a
static per-team correction on top of that baseline over the ~49k-row
historical_matches table:

    lambda_home = mu_home(Elo) * exp(atk_home + def_away)
    lambda_away = mu_away(Elo) * exp(atk_away + def_home)

where atk_t / def_t are log-lambda offsets (positive def = leaky). The weighted
Poisson maximum likelihood is solved by iterative proportional scaling —
deterministic (no RNG), a handful of numpy passes over the rows. Each match is
weighted 0.5^(age_days / half_life): international squads turn over on a 2–4
year cycle, so the default half-life sits in the middle of that range. Fitted
offsets then pass through the shrink/cap policy (ml/models/team_offsets.py):
few-match teams shrink toward 0 and nothing escapes the form-layer-equivalent
hard cap.

Runs OFFLINE only (CLI / CI) and writes ml/models/team_offsets.json
{team_name: {atk, def, n_matches}}. Nothing in the web request path imports
this module — serving only ever reads the JSON, and only when
model_params.json enables it ("team_offsets" is null by default).

Usage:
    PYTHONPATH=backend:. python -m pipeline.fit_attack_defence [--half-life-days N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from ml.features.training_rows import _as_date
from ml.models.params import ModelParams, load_params
from ml.models.poisson import expected_goals_from_elo
from ml.models.team_offsets import shrink_and_cap

#: Decay half-life in days (~3 years) — mid-range of the 2–4-year international
#: squad cycle (FR-5.1). One squad generation back, a match counts half.
DEFAULT_HALF_LIFE_DAYS = 1095

#: Working clamp on RAW offsets during iteration — only a numerical guard for
#: degenerate teams (e.g. zero goals in weighted history); the policy cap in
#: shrink_and_cap is far tighter and is what ships.
_RAW_BOUND = 2.0

_MAX_ITER = 200
_TOL = 1e-10
_FLOOR = 1e-300  # avoids log(0) for teams with zero weighted goals

_OUT_FILE = Path(__file__).resolve().parents[1] / "ml" / "models" / "team_offsets.json"


def decay_weight(match_date, ref_date, half_life_days: int = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Per-day exponential decay: 1.0 at ref_date, 0.5 one half-life back."""
    age_days = max(0, (_as_date(ref_date) - _as_date(match_date)).days)
    return 0.5 ** (age_days / half_life_days)


def fit_offsets(
    rows: list[dict],
    ref_date,
    half_life_days: int = DEFAULT_HALF_LIFE_DAYS,
    params: ModelParams | None = None,
    max_iter: int = _MAX_ITER,
    tol: float = _TOL,
    goal_keys: tuple[str, str] = ("score_home", "score_away"),
) -> dict[int, dict]:
    """Fit shrunk/capped offsets on rows dated STRICTLY before ref_date.

    ``rows`` are enriched backtest rows (pipeline/backtest_data) with leak-free
    pre-match Elo; ``ref_date`` is both the exclusive cutoff and the decay
    reference, so a walk-forward caller passing an edition's first match date
    can never leak the edition into its own fit. Returns
    {team_id: {"atk", "def", "n_matches", "n_eff"}} (offsets in log-lambda
    units, already shrunk toward 0 below the effective-match floor and capped).
    """
    params = params or load_params()
    ref = _as_date(ref_date)
    train = [r for r in rows if _as_date(r["date"]) < ref]
    if not train:
        return {}

    ids = sorted({r["home_id"] for r in train} | {r["away_id"] for r in train})
    index = {tid: i for i, tid in enumerate(ids)}
    n_teams = len(ids)

    h = np.array([index[r["home_id"]] for r in train])
    a = np.array([index[r["away_id"]] for r in train])
    gh = np.array([float(r[goal_keys[0]]) for r in train])
    ga = np.array([float(r[goal_keys[1]]) for r in train])
    w = np.array([decay_weight(r["date"], ref, half_life_days) for r in train])
    mu_h = np.empty(len(train))
    mu_a = np.empty(len(train))
    for i, r in enumerate(train):
        adv = 0.0 if r["is_neutral"] else params.home_adv
        mu_h[i], mu_a[i] = expected_goals_from_elo(
            r["pre_home"], r["pre_away"], adv, params.base, params.beta
        )

    n_eff = np.bincount(h, weights=w, minlength=n_teams) + np.bincount(
        a, weights=w, minlength=n_teams
    )
    n_matches = np.bincount(h, minlength=n_teams) + np.bincount(a, minlength=n_teams)
    # Weighted goal sums are data constants — hoisted out of the loop.
    scored = np.bincount(h, weights=w * gh, minlength=n_teams) + np.bincount(
        a, weights=w * ga, minlength=n_teams
    )
    conceded = np.bincount(h, weights=w * ga, minlength=n_teams) + np.bincount(
        a, weights=w * gh, minlength=n_teams
    )

    atk = np.zeros(n_teams)
    dfn = np.zeros(n_teams)
    for _ in range(max_iter):
        prev_atk, prev_dfn = atk, dfn
        # Iterative scaling: exp(atk_t) <- (weighted goals scored by t) /
        # (weighted lambda mass t was expected to score), holding def fixed.
        lam_h = mu_h * np.exp(atk[h] + dfn[a])
        lam_a = mu_a * np.exp(atk[a] + dfn[h])
        exp_scored = np.bincount(h, weights=w * lam_h, minlength=n_teams) + np.bincount(
            a, weights=w * lam_a, minlength=n_teams
        )
        atk = np.clip(
            atk + np.log(np.maximum(scored, _FLOOR) / np.maximum(exp_scored, _FLOOR)),
            -_RAW_BOUND, _RAW_BOUND,
        )
        # Same update for defence against the refreshed attack.
        lam_h = mu_h * np.exp(atk[h] + dfn[a])
        lam_a = mu_a * np.exp(atk[a] + dfn[h])
        exp_conceded = np.bincount(h, weights=w * lam_a, minlength=n_teams) + np.bincount(
            a, weights=w * lam_h, minlength=n_teams
        )
        dfn = np.clip(
            dfn + np.log(np.maximum(conceded, _FLOOR) / np.maximum(exp_conceded, _FLOOR)),
            -_RAW_BOUND, _RAW_BOUND,
        )
        # Identifiability + level pin: (atk+c, def−c) leaves every lambda
        # unchanged, and a common level shift would just re-tune `base` (an idea
        # already refuted) — so center both to their n_eff-weighted mean and keep
        # offsets strictly RELATIVE to the served baseline.
        atk = atk - np.average(atk, weights=n_eff)
        dfn = dfn - np.average(dfn, weights=n_eff)
        if max(np.abs(atk - prev_atk).max(), np.abs(dfn - prev_dfn).max()) < tol:
            break

    out: dict[int, dict] = {}
    for i, tid in enumerate(ids):
        atk_i, dfn_i = shrink_and_cap(float(atk[i]), float(dfn[i]), float(n_eff[i]))
        out[tid] = {
            "atk": atk_i,
            "def": dfn_i,
            "n_matches": int(n_matches[i]),
            "n_eff": float(n_eff[i]),
        }
    return out


def fit_and_write(
    db,
    out_path: str | Path | None = None,
    half_life_days: int = DEFAULT_HALF_LIFE_DAYS,
    params: ModelParams | None = None,
    goal_keys: tuple[str, str] = ("score_home", "score_away"),
) -> dict:
    """Fit on the full historical_matches replay and write team_offsets.json.

    The store is keyed by team NAME ({name: {atk, def, n_matches}}) so serving
    can look teams up without a DB join. Returns a run summary dict.
    """
    from app.models import Team
    from pipeline.backtest_data import build_enriched_rows

    rows = build_enriched_rows(db)
    if not rows:
        raise ValueError("historical_matches is empty — nothing to fit")
    # Cutoff is exclusive, so step one day past the newest match to include it.
    ref = max(_as_date(r["date"]) for r in rows) + timedelta(days=1)
    offsets = fit_offsets(
        rows, ref, half_life_days=half_life_days, params=params, goal_keys=goal_keys
    )

    # Column-scoped query (id/name is all we need — and it keeps the offline
    # fitter runnable against a dev DB that lags the newest teams migrations).
    names = dict(db.query(Team.id, Team.name).all())
    payload = {
        names[tid]: {
            "atk": round(entry["atk"], 6),
            "def": round(entry["def"], 6),
            "n_matches": entry["n_matches"],
        }
        for tid, entry in offsets.items()
        if tid in names
    }
    out = Path(out_path) if out_path is not None else _OUT_FILE
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {
        "teams": len(payload),
        "matches": len(rows),
        "half_life_days": half_life_days,
        "ref_date": ref.isoformat(),
        "out": str(out),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fit per-team attack/defence offsets (offline, FR-5.1)."
    )
    ap.add_argument("--half-life-days", type=int, default=DEFAULT_HALF_LIFE_DAYS)
    ap.add_argument("--out", default=None, help="output path (default ml/models/team_offsets.json)")
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        summary = fit_and_write(db, out_path=args.out, half_life_days=args.half_life_days)
    finally:
        db.close()
    print(
        f"Fitted offsets for {summary['teams']} teams on {summary['matches']} matches "
        f"(half-life {summary['half_life_days']}d, ref {summary['ref_date']}) "
        f"-> {summary['out']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
