"""T1.6 runner — nested, shadow-only calibrator recut on club football.

Protocol (fixed before the first run):

  Data      Nine PRE-confirmation seasons, 2016-17..2024-25. The consumed
            2025-26 holdout is dropped AT LOAD and a backstop guard raises if a
            single row of it reaches a scoring or fitting path. It is last
            chronologically, so dropping it cannot disturb any earlier rating.

  Outer     For each scored season S (oldest-first), the training block is
            every season STRICTLY BEFORE S. Each candidate's bucket edges and
            per-bucket (t, b) are fitted on that block alone and then scored on
            S. Calibration is therefore never fitted on the outcomes it scores.

  Abstain   A season with fewer than --min-train-seasons prior seasons is
            ABSTAINED, not scored, and never pooled with later data to make up
            the shortfall. Abstentions are reported, not hidden.

  Family    ml.evaluation.club_calibration.CANDIDATES is pre-declared, so the
            multiplicity count is fixed in advance. The recut family is scored
            under both a nominal and a Bonferroni-corrected view.

  Market    De-vigged closing odds are reported as a BENCHMARK only. They are
            never a label and never a feature: no candidate reads them.

Shadow-only: writes nothing, serves nothing, promotes nothing.

Usage::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_club_calibration \\
        --csv-dir <captures> [--emit-json out.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ml.evaluation.calibration import calibrate, effective_gap
from ml.evaluation.club_calibration import (
    CANDIDATES,
    CONFIRM_SEASON,
    REFIT_FAMILY,
    apply_blob,
    assert_holdout_absent,
    brier_one,
    ece,
    fit_segmented,
    log_loss_one,
    occupancy,
    quantile_edges,
    rps_one,
)
from ml.evaluation.club_walkforward import ClubMatch, EloConfig, replay
from ml.evaluation.market_benchmark import devig
from ml.models.params import load_params
from ml.models.poisson import expected_goals_from_elo, outcome_probabilities, score_matrix
from pipeline.club_data_manifest import verify
from pipeline.ingest.club_results import clean_club_results_df

P = load_params()
# division, competition, served home_adv, #202 shipped base
LEAGUES = [("E0", "Premier League", 60.0, 1.30),
           ("SP1", "La Liga", 80.0, 1.20),
           ("D1", "Bundesliga", 60.0, 1.44)]
ODDS_TRIPLES = [("AvgC", ("AvgCH", "AvgCD", "AvgCA")), ("PSC", ("PSCH", "PSCD", "PSCA"))]
_LABEL = {"H": 0, "D": 1, "A": 2}


def load_league(div: str, csv_dir: Path):
    """Load a league's PRE-confirmation seasons. The holdout never enters."""
    frames = []
    for f in sorted(glob.glob(str(csv_dir / f"{div}_*.csv"))):
        code = Path(f).stem.split("_")[1]
        if code == CONFIRM_SEASON:
            continue  # dropped at load — the primary defence
        frames.append(pd.read_csv(f, low_memory=False).assign(season_code=code))
    raw = pd.concat(frames, ignore_index=True)
    trip = next((t for _, t in ODDS_TRIPLES if set(t) <= set(raw.columns)), None)
    keep = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "season_code"]
    df = clean_club_results_df(raw[keep + list(trip or [])].copy())
    for c in (trip or []):
        df[c] = pd.to_numeric(raw.loc[df.index, c], errors="coerce")
    df = df.sort_values("match_date")
    assert_holdout_absent(df.season_code.tolist(), "load_league")
    return df, trip


def build_rows(df, comp: str, home_adv: float, base: float, trip) -> list[dict]:
    """Leak-free pre-match probabilities + gaps + labels, one row per match."""
    ms = [ClubMatch(r.season_code, r.HomeTeam, r.AwayTeam, int(r.FTHG), int(r.FTAG),
                    r.match_date.date().isoformat())
          for r in df.itertuples(index=False)]
    pre = replay(ms, EloConfig(home_adv=home_adv), comp)
    out = []
    for rec, m, pp in zip(df.to_dict("records"), ms, pre):
        lh, la = expected_goals_from_elo(pp[0], pp[1], home_adv=home_adv,
                                         base=base, beta=P.beta)
        raw_probs = outcome_probabilities(score_matrix(lh, la, rho=P.rho))
        mkt = None
        if trip and all(pd.notna(rec.get(c)) and rec.get(c, 0) > 1.0 for c in trip):
            mkt = devig(*(float(rec[c]) for c in trip))
        out.append({
            "season": m.season,
            "raw": raw_probs,
            "gap": effective_gap(pp[0], pp[1], home_adv),
            "label": _LABEL["H" if m.goals_home > m.goals_away
                            else ("A" if m.goals_home < m.goals_away else "D")],
            "market": mkt,
        })
    assert_holdout_absent([r["season"] for r in out], "build_rows")
    return out


def calibrated(row: dict, name: str, blob: dict | None):
    spec = CANDIDATES[name]
    if spec["kind"] == "served":
        return calibrate(row["raw"], P.calibrator, P.temperature, eff_gap=row["gap"])
    if spec["kind"] == "none":
        return row["raw"]
    return apply_blob(row["raw"], blob, row["gap"])


def fit_candidate(name: str, train: list[dict]) -> dict | None:
    spec = CANDIDATES[name]
    if spec["kind"] != "refit":
        return None
    assert_holdout_absent([r["season"] for r in train], f"fit_candidate:{name}")
    gaps = [r["gap"] for r in train]
    edges = spec.get("edges") or quantile_edges(gaps, spec["n_buckets"])
    return fit_segmented([r["raw"] for r in train], [r["label"] for r in train],
                         gaps, edges, min_bucket=spec["min_bucket"])


def season_bootstrap_ci(by_season: dict[str, list[float]], n_boot: int = 2000,
                        seed: int = 12345, alpha: float = 0.05):
    """Percentile CI on the mean per-match delta, resampling WHOLE SEASONS."""
    keys = sorted(by_season)
    pooled = [v for k in keys for v in by_season[k]]
    if not pooled or len(keys) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [v for k in s for v in by_season[k]]
        means.append(sum(vals) / len(vals))
    means.sort()
    lo_i = int((alpha / 2) * n_boot)
    hi_i = min(n_boot - 1, int((1 - alpha / 2) * n_boot))
    return means[lo_i], means[hi_i]


def run_league(div, comp, home_adv, ship_base, csv_dir, min_train_seasons):
    df, trip = load_league(div, csv_dir)
    configs = {"control": P.base, "shipped": ship_base}
    result = {"league": comp, "odds_source": trip[0] if trip else None,
              "identical_configs": ship_base == P.base, "configs": {}}

    for cfg_name, base in configs.items():
        rows = build_rows(df, comp, home_adv, base, trip)
        seasons = sorted({r["season"] for r in rows})
        by_season_rows = defaultdict(list)
        for r in rows:
            by_season_rows[r["season"]].append(r)

        # metric accumulators: cand -> season -> per-match values
        ll = {c: defaultdict(list) for c in CANDIDATES}
        rel = {c: [] for c in CANDIDATES}
        agg = {c: defaultdict(float) for c in CANDIDATES}
        n_tot = 0
        abstained, occ_last, thin_last = [], {}, {}
        mkt_ll, n_mkt = 0.0, 0

        for i, S in enumerate(seasons):
            if i < min_train_seasons:
                abstained.append(S)
                continue
            train = [r for s in seasons[:i] for r in by_season_rows[s]]
            assert_holdout_absent([r["season"] for r in train], "outer-train")
            test = by_season_rows[S]
            assert_holdout_absent([r["season"] for r in test], "outer-test")

            blobs = {c: fit_candidate(c, train) for c in CANDIDATES}
            for c, b in blobs.items():
                if b:
                    occ_last[c] = occupancy([r["gap"] for r in test], b["edges"])
                    thin_last[c] = b["thin_buckets"]

            for r in test:
                for c in CANDIDATES:
                    p = calibrated(r, c, blobs[c])
                    v = log_loss_one(p, r["label"])
                    ll[c][S].append(v)
                    agg[c]["ll"] += v
                    agg[c]["brier"] += brier_one(p, r["label"])
                    agg[c]["rps"] += rps_one(p, r["label"])
                    agg[c]["sharp"] += max(p)
                    agg[c]["n"] += 1
                    rel[c].append((max(p), 1.0 if max(range(3), key=lambda z: p[z])
                                   == r["label"] else 0.0))
                if r["market"]:
                    mkt_ll += log_loss_one(r["market"], r["label"])
                    n_mkt += 1
                n_tot += 1

        ref = "prod_calibrator"
        cands = {}
        for c in CANDIDATES:
            a = agg[c]
            if not a["n"]:
                continue
            deltas = {s: [x - y for x, y in zip(ll[c][s], ll[ref][s])]
                      for s in ll[c]}
            ci = season_bootstrap_ci(deltas) if c != ref else None
            k = len(REFIT_FAMILY)
            ci_bonf = (season_bootstrap_ci(deltas, alpha=0.05 / k)
                       if c in REFIT_FAMILY else None)
            cands[c] = {
                "n": int(a["n"]),
                "log_loss": a["ll"] / a["n"], "brier": a["brier"] / a["n"],
                "rps": a["rps"] / a["n"], "sharpness": a["sharp"] / a["n"],
                "ece": ece(rel[c]),
                "delta_vs_prod": (a["ll"] - agg[ref]["ll"]) / a["n"],
                "ci95": ci, "ci_bonferroni": ci_bonf,
                "per_season_delta": {s: sum(v) / len(v) for s, v in deltas.items()},
                "bucket_occupancy": occ_last.get(c),
                "thin_buckets": thin_last.get(c),
            }
        result["configs"][cfg_name] = {
            "base": base, "n_scored": n_tot, "seasons_scored": seasons[min_train_seasons:],
            "abstained": abstained,
            "market_benchmark": ({"log_loss": mkt_ll / n_mkt, "n": n_mkt}
                                 if n_mkt else None),
            "candidates": cands,
        }
    return result


def format_report(res: dict) -> str:
    L = [f"\n{'=' * 78}", f"{res['league']}   odds={res['odds_source'] or 'NONE'}"]
    for cfg, d in res["configs"].items():
        if cfg == "shipped" and res["identical_configs"]:
            L.append(f"\n  [{cfg}] base={d['base']} — IDENTICAL to control (#202 "
                     f"changed nothing here); results repeat by construction")
        else:
            L.append(f"\n  [{cfg}] base={d['base']}   scored n={d['n_scored']}   "
                     f"seasons={len(d['seasons_scored'])}   abstained={d['abstained']}")
        mb = d["market_benchmark"]
        if mb:
            L.append(f"    market benchmark (de-vigged closing, NOT a feature): "
                     f"LL {mb['log_loss']:.4f} on n={mb['n']}")
        L.append(f"    {'candidate':<22}{'LL':>9}{'dvsProd':>10}{'CI95':>20}"
                 f"{'Brier':>9}{'RPS':>8}{'ECE':>8}{'sharp':>8}")
        for c, m in d["candidates"].items():
            ci = m["ci95"]
            ci_s = f"[{ci[0]:+.4f},{ci[1]:+.4f}]" if ci else "—"
            L.append(f"    {c:<22}{m['log_loss']:>9.4f}{m['delta_vs_prod']:>+10.4f}"
                     f"{ci_s:>20}{m['brier']:>9.4f}{m['rps']:>8.4f}"
                     f"{m['ece']:>8.4f}{m['sharpness']:>8.3f}")
        for c, m in d["candidates"].items():
            if m["bucket_occupancy"]:
                L.append(f"    occupancy {c}: {m['bucket_occupancy']}"
                         + (f"  thin={m['thin_buckets']}" if m["thin_buckets"] else ""))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", type=Path, required=True)
    ap.add_argument("--min-train-seasons", type=int, default=3,
                    help="abstain from scoring a season with fewer prior seasons")
    ap.add_argument("--emit-json", type=Path)
    ap.add_argument("--skip-manifest-check", action="store_true")
    args = ap.parse_args()

    if not args.skip_manifest_check:
        v = verify(args.csv_dir)
        print(f"raw-data manifest: matched={v['matched']} drifted={len(v['drifted'])} "
              f"missing={len(v['missing'])} reproducible={v['reproducible']}")
        if v["drifted"]:
            print("  !! upstream files changed since the recorded capture; "
                  "results are not comparable to the ledger")

    out = [run_league(d, c, h, b, args.csv_dir, args.min_train_seasons)
           for d, c, h, b in LEAGUES]
    for r in out:
        print(format_report(r))
    if args.emit_json:
        args.emit_json.write_text(json.dumps(out, indent=2, default=str))
        print(f"\nwrote {args.emit_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
