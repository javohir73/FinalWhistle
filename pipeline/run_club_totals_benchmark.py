"""Run the D0-B totals benchmark: served O/U 2.5 book vs the closing line.

Pre-registration: `docs/experiments/2026-07-30-d0b-totals-market/
PRE-REGISTRATION.md` (`aa7a445`, corrections `1e207a6`). This runner selects
nothing and writes nothing to production — see §12 of that document.

Usage::

    PYTHONPATH=backend:. python -m pipeline.run_club_totals_benchmark \
        --csv-dir data/raw/club \
        --emit-json /tmp/d0b-totals.json

Offline and hermetic by construction
------------------------------------
`pipeline/experiment_club_eval.py::load_matches` falls back to a live download
when a cached CSV is absent (`experiment_club_eval.py:69-72`). Pointed at
`data/raw/club` — where the three `*_2526` captures do not exist — that would
**fetch the consumed 2025-26 holdout**. This module therefore does not reuse
it: it reads only files that exist, scoped to
`club_data_manifest.pre_confirmation_keys()`, and raises on a missing one
rather than reaching for the network.

Names are joined on ``str.strip`` alone, on BOTH sides, from the same raw CSV
strings. `clean_club_results_df` maps names through `team_mapping`, which is
correct for a DB ingest and wrong here: the totals loader does not, so mixing
the two would silently fail to join every renamed club. Any row that does not
join is a defect, and `--strict-join` (the default) raises on it.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ml.evaluation.club_totals_benchmark import (
    build_matched_totals,
    clustered_deltas,
    information_share,
    score_totals,
)
from ml.evaluation.club_walkforward import (
    CONFIRM_SEASON,
    ClubMatch,
    EloConfig,
    GridConfig,
    replay,
    season_clustered_ci,
)
from pipeline.club_data_manifest import PRE_CONFIRMATION_SEASONS, sha256_of
from pipeline.ingest.football_data import (
    PROVIDER,
    ClosingTotalsUnavailable,
    load_football_data_totals_csv,
    select_totals_family,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

#: league -> (division code, historical competition label, served home adv).
#: Mirrors `pipeline.experiment_club_eval.LEAGUES`; kept local so this runner
#: does not import that module and inherit its network fallback.
LEAGUES: dict[str, tuple[str, str, float]] = {
    "epl": ("E0", "Premier League", 60.0),
    "laliga": ("SP1", "La Liga", 80.0),
    "bundesliga": ("D1", "Bundesliga", 60.0),
}

#: §4 of the pre-registration. The constant baseline's rate is fitted on
#: FIT_SEASONS and every predictor is scored on SCORED_SEASONS; the two are
#: disjoint and `score_totals` enforces that rather than trusting it.
FIT_SEASONS: tuple[str, ...] = ("1920", "2021", "2122", "2223")
SCORED_SEASONS: tuple[str, ...] = ("2324", "2425")


def _read_division_csv(csv_dir: Path, division: str, season: str) -> pd.DataFrame:
    """Read one capture. Raises rather than falling back to the network."""
    path = csv_dir / f"{division}_{season}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is absent. This runner never downloads — a missing capture "
            "is a fact to report, not a fetch to make."
        )
    return pd.read_csv(path)


def load_division_matches(csv_dir: Path, division: str) -> list[ClubMatch]:
    """Every pre-confirmation match for ``division``, oldest-first.

    ALL nine seasons, including the three with no closing totals family: those
    are burn-in for the Elo replay and are never scored. Restricting the replay
    to the six priced seasons would hand 2019-20 a cold-start rating for every
    club and change every probability downstream.
    """
    rows: list[tuple] = []
    for season in PRE_CONFIRMATION_SEASONS:
        df = _read_division_csv(csv_dir, division, season)
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

    # Stable sort by date: Elo is path-dependent and `replay` requires
    # oldest-first. Same-day rows keep file order, as run_club_benchmark does.
    rows.sort(key=lambda t: t[0])
    return [
        ClubMatch(season=s, home=h, away=a, goals_home=gh, goals_away=ga, date=d)
        for d, s, h, a, gh, ga in rows
    ]


def load_division_totals(csv_dir: Path, division: str) -> tuple[list[dict], list[dict]]:
    """Priced over/under rows for ``division``, plus a per-file coverage census.

    Returns (records, census). A file with no closing totals family abstains
    whole and is recorded with ``family=None`` and its row count, so the
    denominator is always visible and the nine structural exclusions are named
    rather than absent.
    """
    records: list[dict] = []
    census: list[dict] = []
    for season in PRE_CONFIRMATION_SEASONS:
        path = csv_dir / f"{division}_{season}.csv"
        df = _read_division_csv(csv_dir, division, season)
        n_rows = int(df["HomeTeam"].notna().sum())
        try:
            family = select_totals_family(df.columns)
        except ClosingTotalsUnavailable as exc:
            census.append({
                "file": path.name, "rows": n_rows, "family": None, "usable": 0,
                "dropped": n_rows, "reason": "no_closing_totals_columns",
                "detail": str(exc), "sha256": sha256_of(path),
            })
            continue
        recs = load_football_data_totals_csv(str(path))
        for r in recs:
            r["season"] = season
        records.extend(recs)
        census.append({
            "file": path.name, "rows": n_rows, "family": family.key,
            "basis": family.basis, "bookmaker": family.bookmaker,
            "usable": len(recs), "dropped": n_rows - len(recs),
            "reason": None if n_rows == len(recs) else "unusable_price_or_score",
            "sha256": sha256_of(path),
        })
    return records, census


def _grids(league: str) -> tuple[EloConfig, GridConfig, GridConfig]:
    """(elo, served_grid, control_grid) for ``league``.

    ``served`` is `pipeline.leagues.club_params_for` — the exact per-league
    configuration in production, `base` override included. ``control`` is
    `club_baseline_params_for` — the pre-override global. The control is the
    only column that is out-of-sample with respect to T1.1, which selected
    `base` on this metric over a superset of the scored seasons.

    NOT `ml.evaluation.backtest.model_probs`, whose defaults
    (`base=1.35, beta=0.0019, rho=0.0`, no calibrator) are what
    `pipeline/run_club_benchmark.py:98` scores and are served by nothing.
    """
    from pipeline.leagues import club_baseline_params_for, club_params_for

    _div, _comp, home_adv = LEAGUES[league]
    served, control = club_params_for(league), club_baseline_params_for(league)

    # `ml/models/odds_blend.py::lambda_total_from_over` inverts THIS market
    # straight into the served lambda sum. With `use_odds` on, the model column
    # would become a function of the market column and this benchmark would
    # converge toward zero while looking like progress. The committed config is
    # pinned by test; this guards a run made against a modified one.
    for name, p in (("served", served), ("control", control)):
        if p.use_odds:
            raise AssertionError(
                f"{league}/{name} has use_odds=True — the odds-blend shadow path "
                "feeds the closing over/under line into the model's lambdas, so "
                "this benchmark would be scoring the market against itself"
            )
    to_grid = lambda p: GridConfig(  # noqa: E731 - a 1-line adapter, not logic
        base=p.base, beta=p.beta, rho=p.rho,
        temperature=p.temperature, calibrator=p.calibrator,
    )
    return EloConfig(home_adv=home_adv), to_grid(served), to_grid(control)


def run_league(league: str, csv_dir: Path, *, n_bootstrap: int = 2000,
               strict_join: bool = True) -> dict:
    """Score one league. Pure orchestration over pure modules."""
    division, competition, _ = LEAGUES[league]
    matches = load_division_matches(csv_dir, division)
    if any(m.season == CONFIRM_SEASON for m in matches):
        raise AssertionError(
            f"{CONFIRM_SEASON} reached the replay — the holdout is consumed and "
            "must never be read by this phase"
        )

    elo, served_grid, control_grid = _grids(league)
    pre = replay(matches, elo, competition)
    priced, census = load_division_totals(csv_dir, division)

    matched, unpriced = build_matched_totals(
        matches, pre, elo, served_grid, control_grid, priced,
    )
    if unpriced and strict_join:
        sample = [(r["date"].isoformat(), r["home_team"], r["away_team"])
                  for r in unpriced[:5]]
        raise AssertionError(
            f"{len(unpriced)} priced rows did not join to a replayed match "
            f"(first {len(sample)}: {sample}). Both sides come from the same "
            "CSVs under str.strip, so a miss is a defect, not missingness."
        )

    result = score_totals(matched, FIT_SEASONS, SCORED_SEASONS)
    rows = result.pop("rows")
    d_mm = result.pop("deltas_model_minus_market")
    d_mc = result.pop("deltas_model_minus_control")

    result["league"] = league
    result["division"] = division
    result["information_share"] = information_share(result)
    result["intervals"] = {}
    for by in ("iso_week", "season"):
        ci = season_clustered_ci(clustered_deltas(rows, d_mm, by), n_bootstrap=n_bootstrap)
        result["intervals"][by] = {
            "n_clusters": len({r.iso_week if by == "iso_week" else r.season for r in rows}),
            "mean": ci["mean"], "ci95": ci["ci95"],
            "role": "PRIMARY (pre-registered)" if by == "iso_week"
                    else "sensitivity — 2 clusters here; does not cover",
        }
    ci_ctl = season_clustered_ci(clustered_deltas(rows, d_mc, "iso_week"),
                                 n_bootstrap=n_bootstrap)
    result["control_interval_iso_week"] = {"mean": ci_ctl["mean"], "ci95": ci_ctl["ci95"]}

    # Pre-registered resolution: the naive MDE from the realized paired sd,
    # reported next to the clustered half-width, which is the honest one.
    n = len(d_mm)
    mean = sum(d_mm) / n
    sd = (sum((x - mean) ** 2 for x in d_mm) / (n - 1)) ** 0.5 if n > 1 else float("nan")
    half = None
    lo_hi = result["intervals"]["iso_week"]["ci95"]
    if lo_hi:
        half = (lo_hi[1] - lo_hi[0]) / 2
    result["resolution"] = {
        "paired_sd": sd,
        "naive_mde_80pct": 2.80 * sd / (n ** 0.5),
        "clustered_ci_half_width": half,
        "resolved": bool(half is not None and abs(mean) > half),
    }
    result["census"] = census
    result["n_replayed"] = len(matches)
    result["n_priced_rows"] = len(priced)
    result["n_unjoined"] = len(unpriced)
    result["params"] = {
        "served": {"base": served_grid.base, "beta": served_grid.beta,
                   "rho": served_grid.rho, "temperature": served_grid.temperature,
                   "calibrator": served_grid.calibrator is not None},
        "control": {"base": control_grid.base, "beta": control_grid.beta,
                    "rho": control_grid.rho, "temperature": control_grid.temperature,
                    "calibrator": control_grid.calibrator is not None},
        "home_adv": elo.home_adv,
    }
    return result


def format_report(results: list[dict]) -> str:
    """Plain-text report. Every rate carries its denominator."""
    out: list[str] = []
    w = out.append
    w("=" * 78)
    w("D0-B — CLUB TOTALS (O/U 2.5) vs THE CLOSING LINE")
    w("=" * 78)
    w(f"provider   : {PROVIDER['provider']} — {PROVIDER['attribution']}")
    w(f"redistrib. : {PROVIDER['redistribution']}")
    w(f"fit seasons: {', '.join(FIT_SEASONS)}   scored: {', '.join(SCORED_SEASONS)}")
    w("SELECTS NOTHING. The served `base` is IN-SAMPLE on this metric (T1.1")
    w("chose it on O/U 2.5 log loss over 1718-2425, a superset of the scored")
    w("window), so a favourable model-vs-market number is NOT an edge.")
    w("")

    for r in results:
        w("-" * 78)
        w(f"{r['league'].upper()}  ({r['division']})   market: {r['market_basis']}")
        w("-" * 78)
        w(f"  replayed {r['n_replayed']} matches over 9 seasons; "
          f"{r['n_priced_rows']} priced; {r['n_unjoined']} unjoined")
        w(f"  scored {r['n_matches']} matches; constant fitted on {r['n_fit']}")
        w(f"  over-rate scored {r['over_rate_scored']:.4f}; "
          f"constant rate {r['constant_rate']:.4f}")
        w("")
        w(f"  {'predictor':<12} {'log loss':>10} {'brier':>9} {'accuracy':>9}")
        for name in ("model", "control", "market", "constant"):
            m = r[name]
            w(f"  {name:<12} {m['log_loss']:>10.4f} {m['brier']:>9.4f} "
              f"{m['accuracy']:>9.4f}")
        w("")
        iw = r["intervals"]["iso_week"]
        ci = iw["ci95"]
        ci_s = f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "n/a"
        w(f"  model - market : {r['model_minus_market']:+.4f}  "
          f"{ci_s}  ({iw['n_clusters']} iso-week clusters)")
        sn = r["intervals"]["season"]
        sci = sn["ci95"]
        w(f"    season-clustered sensitivity: {sn['mean']:+.4f}  "
          f"{f'[{sci[0]:+.4f}, {sci[1]:+.4f}]' if sci else 'n/a'}  "
          f"({sn['n_clusters']} clusters — {sn['role']})")
        cc = r["control_interval_iso_week"]["ci95"]
        w(f"  model - control: {r['model_minus_control']:+.4f}  "
          f"{f'[{cc[0]:+.4f}, {cc[1]:+.4f}]' if cc else 'n/a'}"
          "   <- in-sample advantage, NOT skill")
        w(f"  market - const : {r['market_minus_constant']:+.4f}"
          "   <- the totals information budget")
        share = r["information_share"]
        w(f"  information share captured by the model: "
          f"{'n/a (market does not beat the constant)' if share is None else f'{share:6.1%}'}")
        w("")
        res = r["resolution"]
        w(f"  paired sd {res['paired_sd']:.4f}; naive 80%-power MDE "
          f"{res['naive_mde_80pct']:.4f}; clustered CI half-width "
          f"{res['clustered_ci_half_width']:.4f}")
        w(f"  RESOLVED AT THIS SAMPLE SIZE: {'yes' if res['resolved'] else 'NO'}")
        w("")
        abstained = [c for c in r["census"] if c["family"] is None]
        w(f"  coverage: {len(r['census']) - len(abstained)}/{len(r['census'])} "
          f"captures priced; {len(abstained)} abstained "
          f"({', '.join(c['file'] for c in abstained) or 'none'})")
        w("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", default="data/raw/club", type=Path)
    ap.add_argument("--league", action="append", choices=sorted(LEAGUES),
                    help="repeatable; default all three")
    ap.add_argument("--n-bootstrap", type=int, default=2000)
    ap.add_argument("--emit-json", type=Path)
    ap.add_argument("--allow-unjoined", action="store_true",
                    help="report unjoined rows instead of raising (diagnosis only)")
    args = ap.parse_args(argv)

    leagues = args.league or sorted(LEAGUES)
    results = [
        run_league(lg, args.csv_dir, n_bootstrap=args.n_bootstrap,
                   strict_join=not args.allow_unjoined)
        for lg in leagues
    ]
    print(format_report(results))

    if args.emit_json:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "phase": "D0-B",
            "pre_registration": "docs/experiments/2026-07-30-d0b-totals-market/"
                                "PRE-REGISTRATION.md",
            "selects_nothing": True,
            "model_column_is_in_sample": True,
            "provider": PROVIDER,
            "fit_seasons": list(FIT_SEASONS),
            "scored_seasons": list(SCORED_SEASONS),
            "results": results,
        }
        args.emit_json.write_text(json.dumps(payload, indent=2, default=str))
        log.info("wrote %s", args.emit_json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
