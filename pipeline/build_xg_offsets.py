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
    3. Re-anchor  -> PER CHANNEL c in {atk, def} (fit_offsets centers atk and def
                     separately, so each has its own zero-point mismatch):
                     delta_c = sum_{t in S} n_eff_xg,t * (g_hat_t,c - x_hat_t,c)
                               / sum_{t in S} n_eff_xg,t
                     x_hat'_t,c = x_hat_t,c + delta_c
    4. Blend      -> kappa_t = min(1, sqrt(n_eff_xg,t / FULL_WEIGHT_EFF_MATCHES))
                     offset_t,c = clamp( g_hat_t,c + kappa_t * (x_hat'_t,c - g_hat_t,c) )
                     re-clamped to OFFSET_CAP: delta_c can push x_hat' outside the
                     capped region, so the convex combination is NOT cap-preserving
                     on its own (the spec's "convexity keeps it capped for free" is
                     wrong once delta shifts a channel out) -- enforce it here, not
                     via offsets_for's load-time defence-in-depth clamp.

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
from ml.models.team_offsets import FULL_WEIGHT_EFF_MATCHES, OFFSET_CAP
from pipeline.fit_attack_defence import fit_offsets

_OUT_FILE = Path(__file__).resolve().parents[1] / "ml" / "models" / "team_offsets_xg.json"


def reanchor(goals_offsets: dict[int, dict], xg_offsets: dict[int, dict]) -> dict[str, float]:
    """Per-channel zero-point correction between the goals fit and the xG fit.

    fit_offsets centers atk and def SEPARATELY, each to its own n_eff-weighted
    mean (fit_attack_defence.py:146-147). The goals fit is centered over the full
    population, the xG fit over the covered subset S, so the two fits' zero points
    differ by a DIFFERENT scalar on each channel. Return {"atk": delta_atk,
    "def": delta_def}, each the n_eff_xg-weighted mean gap (g_hat - x_hat) over S,
    so x_hat + delta lands back on the goals frame per channel. Both 0.0 when S is
    empty (undefined -> no-op, not NaN). Applying the atk shift to the def channel
    (the earlier single-scalar form) both used the wrong frame AND could push def
    past OFFSET_CAP.
    """
    zero = {"atk": 0.0, "def": 0.0}
    if not xg_offsets:
        return zero
    shared = [
        (goals_offsets[t], entry)
        for t, entry in xg_offsets.items()
        if t in goals_offsets
    ]
    den = sum(x["n_eff"] for _, x in shared)
    if den <= 0:
        return zero
    return {
        ch: sum(x["n_eff"] * (g[ch] - x[ch]) for g, x in shared) / den
        for ch in ("atk", "def")
    }


def _clamp(v: float) -> float:
    """Clamp a blended offset to the same +/-OFFSET_CAP the fitter caps its own
    outputs at (ml/models/team_offsets.py)."""
    return max(-OFFSET_CAP, min(OFFSET_CAP, v))


def blend_offsets(
    goals_offsets: dict[int, dict], xg_offsets: dict[int, dict], delta: dict[str, float]
) -> dict[int, dict]:
    """offset_t,c = clamp( g_hat_t,c + kappa_t * (x_hat_t,c + delta_c - g_hat_t,c) )
    per channel c in {atk, def}, with a per-team kappa (coverage is per-team, not
    per-stat) and the per-channel re-anchor delta.

    The final blend is re-clamped to OFFSET_CAP HERE, not left to offsets_for's
    load-time clamp: delta_c can push (x_hat + delta_c) outside the capped region,
    so the convex combination is not cap-preserving on its own. Re-clamping at the
    blend keeps the PERSISTED store in-policy (the record endpoint and the A/B
    report read these raw numbers). Teams outside S (kappa=0) reproduce the goals
    offset exactly. Output shape matches fit_and_write's payload:
    {atk, def, n_matches} (n_eff is internal to this blend and not persisted).
    """
    d_atk, d_def = delta["atk"], delta["def"]
    out: dict[int, dict] = {}
    for t, g in goals_offsets.items():
        x = xg_offsets.get(t)
        n_eff_xg = x["n_eff"] if x is not None else 0.0
        kappa = min(1.0, (n_eff_xg / FULL_WEIGHT_EFF_MATCHES) ** 0.5) if n_eff_xg > 0 else 0.0
        if kappa <= 0.0 or x is None:
            atk, dfn = g["atk"], g["def"]
        else:
            atk = _clamp(g["atk"] + kappa * (x["atk"] + d_atk - g["atk"]))
            dfn = _clamp(g["def"] + kappa * (x["def"] + d_def - g["def"]))
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
        f"({summary['xg_teams']} with xG coverage, "
        f"delta_atk={summary['delta']['atk']:.6f} delta_def={summary['delta']['def']:.6f}) "
        f"-> {summary['out']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
