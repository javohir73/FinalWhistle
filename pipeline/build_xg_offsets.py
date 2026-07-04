"""Produce ml/models/team_offsets_xg.json — a goals prior nudged by xG (FR-5.1
xG pivot). Reuses the fit_offsets ML core VERBATIM (see pipeline/fit_attack_defence.py);
this module adds only the re-anchor + kappa-blend documented in
docs/superpowers/specs/2026-07-04-xg-team-offsets-design.md ("The fit (ML
core)", lines 73-110). No new MLE/decay/shrink/cap logic lives here.

Notation (mirrors the spec): for each team t, g_hat_t = goals-fit offset,
x_hat_t = xG-fit offset (both already shrunk/capped by fit_offsets itself). Let
S = teams with any xG coverage (n_eff_xg,t > 0, i.e. present in the xG-fit
output). The blend:

    1. Goals fit  -> {t: g_hat_t}                 (today's fitter, full history)
    2. xG fit     -> {t in S: x_hat_t}             (same fitter, goal_keys=xg_a/xg_b)
    3. Re-anchor  -> delta = sum_{t in S} n_eff_xg,t * (g_hat_t - x_hat_t)
                             / sum_{t in S} n_eff_xg,t
                     x_hat'_t = x_hat_t + delta
    4. Blend      -> kappa_t = min(1, sqrt(n_eff_xg,t / FULL_WEIGHT_EFF_MATCHES))
                     offset_t = g_hat_t + kappa_t * (x_hat'_t - g_hat_t)

S empty (no team has any xG coverage) -> delta is undefined -> skip the xG
nudge entirely and write the goals store unchanged (the kill-switch: a null xG
signal is a no-op, never a crash).

Runs OFFLINE only (CLI / pipeline). Nothing on the web request path imports
this module. Writes ml/models/team_offsets_xg.json, same {team_name: {atk,
def, n_matches}} shape the loader (ml/models/team_offsets.py) already reads.
This store is loaded ONLY by the shadow twin (write_offsets_prediction); it is
never wired into params.team_offsets, so serving is unaffected.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from ml.features.training_rows import _as_date
from ml.models.params import ModelParams
from ml.models.team_offsets import FULL_WEIGHT_EFF_MATCHES
from pipeline.fit_attack_defence import fit_offsets

_OUT_FILE = Path(__file__).resolve().parents[1] / "ml" / "models" / "team_offsets_xg.json"


def reanchor(goals_offsets: dict[int, dict], xg_offsets: dict[int, dict]) -> float:
    """delta = the n_eff_xg-weighted mean gap (g_hat - x_hat) over S = teams
    present in xg_offsets. 0.0 when S is empty (undefined -> no-op, not NaN).
    """
    if not xg_offsets:
        return 0.0
    num = sum(
        entry["n_eff"] * (goals_offsets[t]["atk"] - entry["atk"])
        for t, entry in xg_offsets.items()
        if t in goals_offsets
    )
    den = sum(
        entry["n_eff"] for t, entry in xg_offsets.items() if t in goals_offsets
    )
    if den <= 0:
        return 0.0
    return num / den


def blend_offsets(
    goals_offsets: dict[int, dict], xg_offsets: dict[int, dict], delta: float
) -> dict[int, dict]:
    """offset_t = g_hat_t + kappa_t * (x_hat_t + delta - g_hat_t), applied to
    both atk and def with the SAME kappa (coverage is per-team, not per-stat).
    Teams outside S (kappa=0) reproduce the goals offset exactly. Output shape
    matches fit_and_write's payload: {atk, def, n_matches} (n_eff is internal
    to this blend and not persisted, per the fitter's own store shape).
    """
    out: dict[int, dict] = {}
    for t, g in goals_offsets.items():
        x = xg_offsets.get(t)
        n_eff_xg = x["n_eff"] if x is not None else 0.0
        kappa = min(1.0, (n_eff_xg / FULL_WEIGHT_EFF_MATCHES) ** 0.5) if n_eff_xg > 0 else 0.0
        if kappa <= 0.0 or x is None:
            atk, dfn = g["atk"], g["def"]
        else:
            x_atk = x["atk"] + delta
            x_dfn = x["def"] + delta
            atk = g["atk"] + kappa * (x_atk - g["atk"])
            dfn = g["def"] + kappa * (x_dfn - g["def"])
        out[t] = {"atk": atk, "def": dfn, "n_matches": g["n_matches"]}
    return out


def build_xg_offsets(db, out_path: str | Path | None = None, params: ModelParams | None = None) -> dict:
    """Fit goals + xG offsets over historical_matches, blend, and write
    team_offsets_xg.json. Rows are build_enriched_rows(db) (goals fit) plus the
    same rows carrying xg_a/xg_b (queried directly, since build_enriched_rows
    does not attach them) filtered to xG-covered rows for the xG fit.

    n_eff is NOT persisted by fit_offsets (only n_matches survives to the JSON
    store), so this function runs both fits itself and keeps n_eff in-process
    for the blend — it is never recovered from a written store.
    """
    from app.models import HistoricalMatch, Team
    from pipeline.backtest_data import build_enriched_rows

    rows = build_enriched_rows(db)
    if not rows:
        raise ValueError("historical_matches is empty — nothing to fit")
    ref = max(_as_date(r["date"]) for r in rows) + timedelta(days=1)

    goals_offsets = fit_offsets(rows, ref, params=params)

    # Attach xg_a/xg_b onto the same enriched rows (matched by DB order, which
    # build_enriched_rows preserves from its own date/id-ordered query) so the
    # xG fit walks the identical Elo-replay/decay machinery as the goals fit.
    ordered = (
        db.query(HistoricalMatch)
        .order_by(HistoricalMatch.date.asc(), HistoricalMatch.id.asc())
        .all()
    )
    for row, orm in zip(rows, ordered):
        row["xg_a"] = orm.xg_a
        row["xg_b"] = orm.xg_b
    xg_rows = [r for r in rows if r.get("xg_a") is not None and r.get("xg_b") is not None]

    xg_offsets: dict[int, dict] = {}
    if xg_rows:
        xg_offsets = fit_offsets(xg_rows, ref, params=params, goal_keys=("xg_a", "xg_b"))

    delta = reanchor(goals_offsets, xg_offsets)
    if not xg_offsets:
        blended = {
            t: {"atk": g["atk"], "def": g["def"], "n_matches": g["n_matches"]}
            for t, g in goals_offsets.items()
        }
    else:
        blended = blend_offsets(goals_offsets, xg_offsets, delta)

    names = dict(db.query(Team.id, Team.name).all())
    payload = {
        names[tid]: {
            "atk": round(entry["atk"], 6),
            "def": round(entry["def"], 6),
            "n_matches": entry["n_matches"],
        }
        for tid, entry in blended.items()
        if tid in names
    }
    out = Path(out_path) if out_path is not None else _OUT_FILE
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {
        "teams": len(payload),
        "matches": len(rows),
        "xg_covered_matches": len(xg_rows),
        "xg_teams": len(xg_offsets),
        "delta": delta,
        "ref_date": ref.isoformat(),
        "out": str(out),
    }


def main() -> int:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        summary = build_xg_offsets(db)
    finally:
        db.close()
    print(
        f"Built xG-nudged offsets for {summary['teams']} teams "
        f"({summary['xg_teams']} with xG coverage, delta={summary['delta']:.6f}) "
        f"-> {summary['out']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
