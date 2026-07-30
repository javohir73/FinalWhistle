"""Run E1.1: does a per-team tempo channel earn its complexity on club data?

Pre-registration: `docs/experiments/2026-07-30-e1-tempo-channel/
SELECTION-PRE-REGISTRATION.md` (`3989145`, appendix `758963a`), both pushed
before this file existed. **Selects a candidate; promotes nothing.**

Usage::

    PYTHONPATH=backend:. python -m pipeline.run_e1_tempo \
        --csv-dir data/raw/club --emit-json /tmp/e1.json

Offline and hermetic
--------------------
`pipeline/experiment_club_eval.py::load_matches` downloads any absent cache, so
pointed at `data/raw/club` it would fetch the consumed 2025-26 holdout
(§12). This runner reads only files that exist and raises otherwise.

The fitter is `pipeline.fit_attack_defence.fit_offsets` — FR-5's own, reached
through the additive `policy` seam (Appendix A1) rather than reimplemented, so
E1 is testing that fitter on club data rather than a lookalike free to diverge.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from ml.evaluation.club_tempo import (
    CAP_SENSITIVITY,
    GRID,
    MIN_PRIOR_MATCHES,
    TempoPoint,
    loss_1x2_offsets,
    loss_totals_offsets,
    offset_diagnostics,
    walk_forward_tempo,
)
from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
    replay,
    season_clustered_ci,
)
from ml.models.team_offsets import policy_with
from pipeline.club_data_manifest import PRE_CONFIRMATION_SEASONS, sha256_of
from pipeline.fit_attack_defence import fit_offsets

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

LEAGUES: dict[str, tuple[str, str, float]] = {
    "epl": ("E0", "Premier League", 60.0),
    "laliga": ("SP1", "La Liga", 80.0),
    "bundesliga": ("D1", "Bundesliga", 60.0),
}

#: §5. `1617`/`1718` are burn-in: too little prior history to fit an offset, so
#: scoring them would measure cold-start behaviour rather than the candidate.
SCORED_SEASONS: tuple[str, ...] = ("1819", "1920", "2021", "2122", "2223", "2324", "2425")

#: §7. Seed 26, passed explicitly — `season_clustered_ci` defaults to 12345 and
#: D0-B's first cut reported intervals drawn with that unregistered default.
BOOTSTRAP_SEED = 26

#: §7. One family x one primary metric x three leagues. The grid does not enter
#: k: grid points are selected inside the walk-forward, not tested against the
#: gate. Bonferroni -> each league needs its 98.3% interval to exclude zero.
BONFERRONI_K = 3
CORRECTED_ALPHA = 0.05 / BONFERRONI_K

#: §7. Declared in advance and separate from significance: a resolved gain below
#: this does not justify a per-team parameter store, a fitting job and a serving
#: seam. Landing under it is recorded as "real but not worth serving".
PRACTICAL_FLOOR = 0.005

#: §S4. Above this, the fit is reporting the policy bound rather than tempo.
MAX_SATURATED_FRAC = 0.20


def _read_csv(csv_dir: Path, division: str, season: str) -> pd.DataFrame:
    path = csv_dir / f"{division}_{season}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is absent. This runner never downloads — a missing capture "
            "is a fact to report, not a fetch to make."
        )
    return pd.read_csv(path)


def load_matches(csv_dir: Path, division: str) -> list[ClubMatch]:
    """Every pre-confirmation match, oldest-first. Never `2526`, never a fetch."""
    rows: list[tuple] = []
    for season in PRE_CONFIRMATION_SEASONS:
        df = _read_csv(csv_dir, division, season)
        dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        for i, r in df.iterrows():
            d = dates.iloc[i]
            if pd.isna(d):
                continue
            try:
                gh, ga = int(r["FTHG"]), int(r["FTAG"])
            except (KeyError, TypeError, ValueError):
                continue
            home, away = str(r["HomeTeam"]).strip(), str(r["AwayTeam"]).strip()
            if not home or not away or home == away:
                continue
            rows.append((d.date().isoformat(), season, home, away, gh, ga))
    rows.sort(key=lambda t: t[0])  # Elo is path-dependent; oldest-first required
    return [
        ClubMatch(season=s, home=h, away=a, goals_home=gh, goals_away=ga, date=d)
        for d, s, h, a, gh, ga in rows
    ]


def make_fitter(matches, pre, params, home_adv: float):
    """Build the ``fit(cutoff_iso, point) -> Offsets`` callable E1 injects.

    Rows are shaped for FR-5's `fit_offsets`, which filters to
    ``date < ref_date`` itself and uses ``ref_date`` as the decay reference —
    so a cutoff of the season's first kickoff cannot leak that season into its
    own fit.

    Club names key the result directly; the fitter's ``home_id``/``away_id`` are
    opaque to it, so passing names is legitimate and avoids an id table whose
    only job would be to be reversed again.
    """
    rows = [
        {
            "date": date.fromisoformat(m.date),
            "home_id": m.home, "away_id": m.away,
            "pre_home": p[0], "pre_away": p[1],
            "is_neutral": False,          # club matches never are
            "score_home": m.goals_home, "score_away": m.goals_away,
        }
        for m, p in zip(matches, pre)
    ]

    def fit(cutoff_iso: str, point: TempoPoint) -> dict:
        fitted = fit_offsets(
            rows,
            date.fromisoformat(cutoff_iso),
            half_life_days=point.half_life_days,
            params=params,
            policy=policy_with(cap=point.cap, full_weight_eff=point.n0),
        )
        # §8: below the floor a club falls back to served behaviour EXACTLY.
        # The shrink ramp alone still multiplies a noisy fit by a small number;
        # this is a hard zero, not a small guess.
        #
        # Kept in the dict as an explicit (0.0, 0.0) rather than dropped. Both
        # spellings behave identically at lookup, but dropping them makes the
        # zeroed-club count in the diagnostics silently zero — a coverage number
        # that reads as "every club was modelled" precisely when it was not.
        return {
            team: ((v["atk"], v["def"]) if v["n_matches"] >= MIN_PRIOR_MATCHES
                   else (0.0, 0.0))
            for team, v in fitted.items()
        }

    return fit, rows


def _interval(deltas: dict, n_bootstrap: int, alpha: float) -> dict:
    """Cluster bootstrap at the Bonferroni-corrected level, with the §7 verdict.

    `season_clustered_ci` is hardcoded to 95%, so the corrected interval is
    computed here from the same resampling scheme rather than by rescaling a
    95% width — which would assume normality the bootstrap exists to avoid.
    """
    import random as _random

    keys = sorted(deltas)
    pooled = [v for k in keys for v in deltas[k]]
    if not pooled:
        return {"n": 0, "mean": float("nan"), "ci": None, "verdict": "no data"}
    mean = sum(pooled) / len(pooled)

    rng = _random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(n_bootstrap):
        sampled = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [v for k in sampled for v in deltas[k]]
        means.append(sum(vals) / len(vals))
    means.sort()
    lo = means[int((alpha / 2) * n_bootstrap)]
    hi = means[min(n_bootstrap - 1, int((1 - alpha / 2) * n_bootstrap))]

    half = (hi - lo) / 2
    n = len(pooled)
    sd = (sum((x - mean) ** 2 for x in pooled) / (n - 1)) ** 0.5 if n > 1 else float("nan")
    # A zero-width interval is not certainty, it is the absence of measurement:
    # every resample drew the same clusters, so the bootstrap saw no variation
    # to report. `season_clustered_ci`'s own docstring warns about exactly this
    # ("an interval that looks certain precisely because it measured nothing"),
    # and without this branch a degenerate fit would print CREDIBLE.
    if half <= 0.0:
        verdict = "DEGENERATE — zero-width interval, nothing was measured"
    # §7: the rule D0-B broke. |mean| <= half-width prints UNRESOLVED, never a
    # direction and never "no effect".
    elif abs(mean) <= half:
        verdict = "UNRESOLVED at this sample size"
    elif hi < 0:
        verdict = "CANDIDATE BETTER (credible)"
    elif lo > 0:
        verdict = "CANDIDATE WORSE (credible)"
    else:
        verdict = "UNRESOLVED at this sample size"
    return {
        "n": n, "n_clusters": len(keys), "mean": mean, "ci": (lo, hi),
        "half_width": half, "paired_sd": sd,
        "naive_mde_80pct": 2.80 * sd / (n ** 0.5) if n else float("nan"),
        "excludes_zero": bool(half > 0.0 and (hi < 0 or lo > 0)),
        "verdict": verdict,
    }


def run_league(league: str, csv_dir: Path, *, n_bootstrap: int = 2000) -> dict:
    division, competition, home_adv = LEAGUES[league]
    from pipeline.leagues import club_params_for

    matches = load_matches(csv_dir, division)
    if any(m.season == CONFIRM_SEASON for m in matches):
        raise AssertionError(f"{CONFIRM_SEASON} reached the replay; it is consumed")

    params = club_params_for(league)
    elo = EloConfig(home_adv=home_adv)
    grid = GridConfig(base=params.base, beta=params.beta, rho=params.rho,
                      temperature=params.temperature, calibrator=params.calibrator)
    pre = replay(matches, elo, competition)
    fit, _rows = make_fitter(matches, pre, params, home_adv)

    primary = walk_forward_tempo(
        matches, pre, elo, grid, points=GRID, fit=fit,
        loss=loss_totals_offsets, scored_seasons=SCORED_SEASONS,
    )
    # The guardrail scores THE SAME selected point — a 1X2 re-selection would be
    # a second candidate, and §6 makes 1X2 non-inferiority, not a second gate.
    by_season: dict[str, list[int]] = {}
    for i, m in enumerate(matches):
        by_season.setdefault(m.season, []).append(i)
    guard: dict[str, list[float]] = {}
    for season, point in primary["chosen"].items():
        idx = by_season[season]
        ms = [matches[i] for i in idx]
        ps = [pre[i] for i in idx]
        cand = loss_1x2_offsets(ms, ps, elo, grid,
                                offsets=primary["fitted"][point][season])
        ctrl = loss_1x2_offsets(ms, ps, elo, grid, offsets=None)
        guard[season] = [c - k for c, k in zip(cand, ctrl)]

    diag_point = primary["chosen"].get(SCORED_SEASONS[-1], GRID[0])
    diagnostics = offset_diagnostics(primary["fitted"][diag_point], diag_point.cap)

    sensitivity = {}
    for point in CAP_SENSITIVITY:
        wf = walk_forward_tempo(
            matches, pre, elo, grid, points=(point,), fit=fit,
            loss=loss_totals_offsets, scored_seasons=SCORED_SEASONS,
        )
        sensitivity[point.label()] = _interval(wf["deltas"], n_bootstrap, CORRECTED_ALPHA)

    return {
        "league": league, "division": division,
        "n_replayed": len(matches),
        "n_scored": sum(len(v) for v in primary["deltas"].values()),
        "params": {"base": grid.base, "beta": grid.beta, "rho": grid.rho,
                   "home_adv": home_adv, "calibrator": grid.calibrator is not None},
        "chosen": {s: p.label() for s, p in primary["chosen"].items()},
        "primary": _interval(primary["deltas"], n_bootstrap, CORRECTED_ALPHA),
        "guardrail_1x2": _interval(guard, n_bootstrap, CORRECTED_ALPHA),
        "diagnostics": diagnostics,
        "cap_sensitivity": sensitivity,
    }


def stop_conditions(results: list[dict]) -> list[str]:
    """§10, applied mechanically rather than by narration."""
    fired: list[str] = []
    prim = [r["primary"] for r in results]
    if all(not p["excludes_zero"] for p in prim):
        scope = (", ".join(r["league"] for r in results)
                 if len(results) < BONFERRONI_K else "all three leagues")
        fired.append(
            f"S1 — the primary effect is UNRESOLVED in {scope}. Recorded as a "
            "negative result. The grid is NOT widened and the candidate is NOT "
            "re-specified."
            + ("" if len(results) >= BONFERRONI_K else
               "  (PARTIAL RUN: fewer than the pre-registered three leagues were "
               "scored, so this is not yet the phase's S1 determination.)")
        )
    better = [r for r, p in zip(results, prim) if p["excludes_zero"] and p["mean"] < 0]
    if better and all(abs(r["primary"]["mean"]) < PRACTICAL_FLOOR for r in better):
        fired.append(
            f"S2 — every credible improvement is below the {PRACTICAL_FLOOR} nat "
            "practical floor. Real but not worth serving."
        )
    worse_guard = [r["league"] for r in results
                   if r["guardrail_1x2"]["excludes_zero"] and r["guardrail_1x2"]["mean"] > 0]
    if worse_guard:
        fired.append(
            f"S3 — the 1X2 guardrail fails in {', '.join(worse_guard)}: the "
            "candidate is credibly worse on 1X2. No search for a configuration "
            "that satisfies both."
        )
    sat = [r["league"] for r in results
           if r["diagnostics"].get("saturated_frac", 0.0) > MAX_SATURATED_FRAC]
    if sat:
        fired.append(
            f"S4 — offsets are cap-saturated for >{MAX_SATURATED_FRAC:.0%} of clubs "
            f"in {', '.join(sat)}. That is a fitting defect, not a result."
        )
    return fired


def format_report(results: list[dict], fired: list[str]) -> str:
    out: list[str] = []
    w = out.append
    w("=" * 78)
    w("E1.1 — PER-TEAM TEMPO CHANNEL (attack/defence offsets), CLUB DATA")
    w("=" * 78)
    w(f"scored seasons : {', '.join(SCORED_SEASONS)}   (1617/1718 are burn-in)")
    w(f"bootstrap      : seed {BOOTSTRAP_SEED}, season-clustered, "
      f"Bonferroni k={BONFERRONI_K} -> {100*(1-CORRECTED_ALPHA):.1f}% intervals")
    w(f"practical floor: {PRACTICAL_FLOOR} nats (separate from significance)")
    w("SELECTS ONLY. Nothing is promoted; 2526 is consumed, so E1 cannot confirm.")
    w("")
    for r in results:
        p, g, d = r["primary"], r["guardrail_1x2"], r["diagnostics"]
        w("-" * 78)
        w(f"{r['league'].upper()} ({r['division']})   base={r['params']['base']} "
          f"replayed={r['n_replayed']} scored={r['n_scored']}")
        w("-" * 78)
        ci = lambda e: f"[{e['ci'][0]:+.4f}, {e['ci'][1]:+.4f}]" if e["ci"] else "n/a"
        w(f"  O/U 2.5 (PRIMARY)  {p['mean']:+.4f}  {ci(p)}  "
          f"sd {p['paired_sd']:.4f}  MDE80 {p['naive_mde_80pct']:.4f}")
        w(f"                     {p['verdict']}")
        w(f"  1X2 (guardrail)    {g['mean']:+.4f}  {ci(g)}")
        w(f"                     {g['verdict']}")
        w(f"  offsets: {d['n']} club-seasons, {d['zeroed_frac']:.1%} zeroed, "
          f"{d['saturated_frac']:.1%} cap-saturated")
        w(f"  tempo (atk-def) sd {d.get('tempo_sd', float('nan')):.4f} "
          f"range [{d.get('tempo_min', float('nan')):+.4f}, "
          f"{d.get('tempo_max', float('nan')):+.4f}]")
        picks = sorted(set(r["chosen"].values()))
        w(f"  grid points chosen: {', '.join(picks)}")
        w("  cap sensitivity (reported, never eligible to win):")
        for label, e in r["cap_sensitivity"].items():
            w(f"    {label:<24} {e['mean']:+.4f}  {ci(e)}  {e['verdict']}")
        w("")
    w("=" * 78)
    w("STOP CONDITIONS (§10)")
    w("=" * 78)
    if fired:
        for f in fired:
            w(f"  FIRED: {f}")
    else:
        w("  none fired")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", default="data/raw/club", type=Path)
    ap.add_argument("--league", action="append", choices=sorted(LEAGUES))
    ap.add_argument("--n-bootstrap", type=int, default=2000)
    ap.add_argument("--emit-json", type=Path)
    args = ap.parse_args(argv)
    if args.n_bootstrap < 1:
        ap.error("--n-bootstrap must be >= 1")

    leagues = args.league or sorted(LEAGUES)
    results = [run_league(lg, args.csv_dir, n_bootstrap=args.n_bootstrap)
               for lg in leagues]
    fired = stop_conditions(results)
    print(format_report(results, fired))

    if args.emit_json:
        fingerprints = {}
        for lg in leagues:
            div = LEAGUES[lg][0]
            for s in PRE_CONFIRMATION_SEASONS:
                p = args.csv_dir / f"{div}_{s}.csv"
                if p.exists():
                    fingerprints[p.name] = sha256_of(p)
        args.emit_json.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "phase": "E1.1",
            "pre_registration": "docs/experiments/2026-07-30-e1-tempo-channel/"
                                "SELECTION-PRE-REGISTRATION.md",
            "selects_only": True,
            "promotes_nothing": True,
            "confirmation_available": False,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bonferroni_k": BONFERRONI_K,
            "practical_floor": PRACTICAL_FLOOR,
            "scored_seasons": list(SCORED_SEASONS),
            "results": results,
            "stop_conditions_fired": fired,
            "input_sha256": fingerprints,
        }, indent=2, default=str))
        log.info("wrote %s", args.emit_json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
