"""Reconciliation + SECONDARY market benchmark from independent sources.

Two reports, both read-only:

1. **Reconciliation.** Where independent providers disagree with our stored
   result, or could not be resolved to a Match at all. Disagreement is
   REPORTED, never applied -- nothing here overwrites a score, a fixture or a
   rating.

2. **Secondary market benchmark.** Per-source closing 1X2 log loss against our
   frozen production predictions.

   This is SECONDARY BY CONSTRUCTION and never replaces anything. The
   pre-registered baseline remains the API-Football `odds` comparison inside
   `run_calibrator_benchmark.py`, which this module does not touch, read from,
   or modify. Every column here is labelled by its source; any consensus across
   sources would be a NEW predictor rather than evidence and is not computed.

Statistical spine, enforced here and by tests:
  - One finished match is n=1. Sources, bookmakers and snapshots are COLUMNS.
    n is the count of distinct finished matches, never of rows.
  - Only 2026-27 Bundesliga matches can count toward the live q3 confirmation
    gate. Training seasons (2016-17..2024-25) and the consumed 2025-26 holdout
    may appear for provenance/benchmarking and are structurally barred from the
    confirmation counter by `LIVE_VALIDATION_SEASON_START`.
  - Only snapshots strictly BEFORE kickoff are admissible.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.models import (
    Match,
    Prediction,
    ValidationFixtureObservation,
    ValidationMarketSnapshot,
)
from pipeline.generate_predictions import variant_model_version_for

__all__ = ["reconciliation_report", "secondary_market_benchmark", "format_report"]

_EPS = 1e-12

#: The live q3 confirmation window opens with the 2026-27 season. Anything
#: earlier is provenance or benchmarking only and can never inflate the gate.
LIVE_VALIDATION_SEASON_START = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Treat a stored datetime as UTC.

    SQLite hands back naive datetimes while Postgres returns aware ones, and
    the module constants are aware. Comparing the two raises, so every stored
    timestamp is normalized at the boundary rather than at each comparison.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _label(m: Match) -> int | None:
    if m.score_home is None or m.score_away is None:
        return None
    return 0 if m.score_home > m.score_away else (1 if m.score_home == m.score_away else 2)


def _effective_observations(db) -> tuple[list, int]:
    """The CURRENT observation per (source, source_event_id), plus how many
    earlier revisions it supersedes.

    The table is append-only, so a provider correcting 2-1 to 1-1 leaves the
    original row in place. Evaluating every revision would report that
    correction as a permanent disagreement. History is preserved; only the
    latest effective row is judged.

    Ordering: `source_updated_at`, then `retrieved_at`, then `id`. A NULL
    provider stamp sorts OLDEST (it carries no recency claim) rather than
    winning by accident.
    """
    latest: dict[tuple, object] = {}
    superseded = 0
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def rank(o):
        return (_aware(o.source_updated_at) or epoch,
                _aware(o.retrieved_at) or epoch, o.id)

    for obs in db.query(ValidationFixtureObservation).all():
        key = (obs.source, obs.source_event_id)
        cur = latest.get(key)
        if cur is None:
            latest[key] = obs
        elif rank(obs) > rank(cur):
            latest[key] = obs
            superseded += 1
        else:
            superseded += 1
    return list(latest.values()), superseded


def reconciliation_report(db) -> dict:
    """Unmatched observations and score disagreements, per source.

    Judged on the CURRENT observation per (source, event) only -- see
    `_effective_observations`. Superseded revisions stay in the table and are
    counted, not re-litigated.
    """
    per_source: dict[str, dict] = defaultdict(
        lambda: {"observations": 0, "matched": 0, "unmatched": 0, "conflict": 0,
                 "score_agreements": 0, "score_disagreements": 0})
    unmatched_examples: list[dict] = []
    disagreements: list[dict] = []

    effective, superseded = _effective_observations(db)
    for obs in effective:
        s = per_source[obs.source]
        s["observations"] += 1
        s[obs.reconciliation_status] = s.get(obs.reconciliation_status, 0) + 1

        if obs.reconciliation_status != "matched":
            if len(unmatched_examples) < 25:
                unmatched_examples.append({
                    "source": obs.source, "event": obs.source_event_id,
                    "raw": f"{obs.raw_home_label} v {obs.raw_away_label}",
                    "status": obs.reconciliation_status, "note": obs.reconciliation_note,
                })
            continue
        if obs.score_home is None or obs.score_away is None:
            continue
        m = db.get(Match, obs.match_id)
        if m is None or m.score_home is None or m.score_away is None:
            continue
        if (m.score_home, m.score_away) == (obs.score_home, obs.score_away):
            s["score_agreements"] += 1
        else:
            s["score_disagreements"] += 1
            disagreements.append({
                "source": obs.source, "match_id": m.id,
                "ours": f"{m.score_home}-{m.score_away}",
                "theirs": f"{obs.score_home}-{obs.score_away}",
                "fixture": f"{obs.raw_home_label} v {obs.raw_away_label}",
                "action": "REPORTED ONLY -- nothing overwritten",
            })

    return {"per_source": dict(per_source),
            "effective_observations": len(effective),
            "superseded_revisions": superseded,
            "unmatched_examples": unmatched_examples,
            "score_disagreements": disagreements,
            "clean": not disagreements and not unmatched_examples}


def _closing_by_source(db, match: Match) -> dict[str, dict]:
    """Latest COHERENT pre-kickoff de-vigged 1X2 snapshot, per source.

    "Coherent" means all three outcomes came from ONE snapshot: the same
    source, bookmaker, market and `captured_at`. Selecting the latest row per
    OUTCOME and stitching them together would fabricate a triple that never
    existed at any instant -- three prices from three different times,
    presented as a closing line.

    Among that source's complete snapshots, the LATEST admissible one wins --
    not the alphabetically first bookmaker, which has nothing to do with being
    closest to kickoff. Ties (same captured_at, different books) break
    deterministically on (bookmaker_key, source_market_id).
    """
    if match.kickoff_utc is None:
        return {}
    kickoff = _aware(match.kickoff_utc)

    # Exact snapshot identity: everything that must agree for a triple to be real.
    groups: dict[tuple, dict[str, float]] = defaultdict(dict)
    for r in (db.query(ValidationMarketSnapshot)
              .filter(ValidationMarketSnapshot.match_id == match.id).all()):
        captured = _aware(r.captured_at)
        if captured is None or captured >= kickoff:
            continue  # at or after kickoff is inadmissible, never clamped
        if r.implied_prob_devig is None:
            continue
        groups[(r.source, r.bookmaker_key or "", r.source_market_id, captured)][
            r.outcome] = r.implied_prob_devig

    best: dict[str, tuple] = {}
    for (source, book, market, captured), triple in groups.items():
        if set(triple) != {"home", "draw", "away"}:
            continue  # incomplete snapshot: not a closing line
        total = sum(triple.values())
        if total <= 0:
            continue
        # Latest wins; deterministic tie-break so reruns agree.
        rank = (captured, book, market)
        if source not in best or rank > best[source][0]:
            best[source] = (rank, {k: v / total for k, v in triple.items()},
                            {"bookmaker_key": book, "source_market_id": market,
                             "captured_at": captured})
    return {src: {"probs": probs, "meta": meta} for src, (_rank, probs, meta)
            in best.items()}


def _frozen_variant(db, match: Match, production_version: str, variant: str):
    """Latest pre-kickoff twin row for ``variant``, or None.

    Same freeze rule as production: `created_at` present and strictly before
    kickoff. A twin written late is not admissible evidence, and is dropped
    rather than clamped.
    """
    tag = variant_model_version_for(production_version, variant)
    return (db.query(Prediction)
            .filter(Prediction.match_id == match.id,
                    Prediction.model_version == tag,
                    Prediction.created_at.isnot(None),
                    Prediction.created_at < match.kickoff_utc)
            .order_by(Prediction.created_at.desc(), Prediction.id.desc())
            .first())


def secondary_market_benchmark(db, *, live_only: bool = True,
                               variant: str = "cal_q3") -> dict:
    """Per-source closing benchmark vs our frozen production predictions.

    Optionally also reports the ``variant`` twin (default the T1.6 q3
    recalibrator) on the EXACT SAME matched rows.

    The q3 column is strictly additive: a match with no admissible twin still
    counts in full toward the production and source figures, and is simply
    absent from the q3 pairing. Letting missing twins shrink the source counts
    would silently change what the secondary benchmark is measuring. Paired
    coverage is therefore reported separately, per source.

    The primary confirmation gate stays wholly in
    `run_calibrator_benchmark.py`; nothing here can promote anything.
    """
    per_source: dict[str, dict] = defaultdict(
        lambda: {"n_matches": 0, "source_ll": 0.0, "model_ll": 0.0,
                 "n_paired_variant": 0, "variant_ll": 0.0,
                 "model_ll_on_variant_rows": 0.0, "source_ll_on_variant_rows": 0.0})
    match_ids: set[int] = set()
    variant_match_ids: set[int] = set()
    excluded_pre_live = 0

    for m in (db.query(Match).filter(Match.status == "finished")
              .filter(Match.score_home.isnot(None),
                      Match.score_away.isnot(None)).all()):
        label = _label(m)
        if label is None or m.kickoff_utc is None:
            continue
        if _aware(m.kickoff_utc) < LIVE_VALIDATION_SEASON_START:
            excluded_pre_live += 1
            if live_only:
                continue
        pred = (db.query(Prediction)
                .filter(Prediction.match_id == m.id,
                        Prediction.is_shadow.is_(False),
                        Prediction.created_at.isnot(None),
                        Prediction.created_at < m.kickoff_utc)
                .order_by(Prediction.created_at.desc(), Prediction.id.desc())
                .first())
        if pred is None:
            continue
        model = (pred.prob_home_win, pred.prob_draw, pred.prob_away_win)

        twin = _frozen_variant(db, m, pred.model_version, variant)
        twin_probs = ((twin.prob_home_win, twin.prob_draw, twin.prob_away_win)
                      if twin is not None else None)

        for source, snap in _closing_by_source(db, m).items():
            probs = snap["probs"]
            s = per_source[source]
            s["n_matches"] += 1
            source_ll = -math.log(max(probs[("home", "draw", "away")[label]], _EPS))
            model_ll = -math.log(max(model[label], _EPS))
            s["source_ll"] += source_ll
            s["model_ll"] += model_ll
            match_ids.add(m.id)

            if twin_probs is not None:
                # Paired subset only. Production/source totals above already
                # counted this match and are unaffected either way.
                s["n_paired_variant"] += 1
                s["variant_ll"] += -math.log(max(twin_probs[label], _EPS))
                s["model_ll_on_variant_rows"] += model_ll
                s["source_ll_on_variant_rows"] += source_ll
                variant_match_ids.add(m.id)

    out = {}
    for source, s in sorted(per_source.items()):
        n = s["n_matches"]
        entry = {
            "n_matches": n,
            "source_log_loss": s["source_ll"] / n,
            "model_log_loss_on_same": s["model_ll"] / n,
            "delta_model_minus_source": (s["model_ll"] - s["source_ll"]) / n,
            "variant": None,
        }
        nv = s["n_paired_variant"]
        if nv:
            entry["variant"] = {
                "name": variant,
                "n_paired": nv,
                "coverage": nv / n,
                "variant_log_loss": s["variant_ll"] / nv,
                # Re-stated on the PAIRED SUBSET so the deltas compare like
                # with like -- never against the full-sample production figure.
                "model_log_loss_on_paired": s["model_ll_on_variant_rows"] / nv,
                "source_log_loss_on_paired": s["source_ll_on_variant_rows"] / nv,
                "delta_variant_minus_model": (
                    s["variant_ll"] - s["model_ll_on_variant_rows"]) / nv,
                "delta_variant_minus_source": (
                    s["variant_ll"] - s["source_ll_on_variant_rows"]) / nv,
            }
        out[source] = entry

    return {
        "status": "SECONDARY — does not replace the pre-registered "
                  "API-Football baseline in run_calibrator_benchmark.py",
        "live_only": live_only,
        "variant": variant,
        "excluded_pre_2026_27_matches": excluded_pre_live,
        "distinct_matches": len(match_ids),
        "distinct_matches_with_variant": len(variant_match_ids),
        "by_source": out,
    }


def format_report(recon: dict, bench: dict) -> str:
    L = ["Independent validation sources — reconciliation", ""]
    if not recon["per_source"]:
        L.append("  no observations ingested yet (sources are default OFF)")
    else:
        L.append(f"  judged on {recon['effective_observations']} CURRENT "
                 f"observations; {recon['superseded_revisions']} superseded "
                 "revision(s) retained but not re-litigated")
    for source, s in sorted(recon["per_source"].items()):
        L.append(f"  {source:<20} obs={s['observations']:<5} matched={s['matched']:<5} "
                 f"unmatched={s['unmatched']:<4} conflict={s['conflict']:<3} "
                 f"score agree={s['score_agreements']} disagree={s['score_disagreements']}")
    for d in recon["score_disagreements"][:10]:
        L.append(f"    ! {d['source']} match {d['match_id']} {d['fixture']}: "
                 f"ours {d['ours']} vs theirs {d['theirs']} — {d['action']}")
    for u in recon["unmatched_examples"][:10]:
        L.append(f"    ? {u['source']} {u['raw']}: {u['status']} — {u['note']}")

    L += ["", "SECONDARY market benchmark (per source; NOT the pre-registered baseline)",
          f"  {bench['status']}",
          f"  distinct finished matches counted: {bench['distinct_matches']} "
          f"(one match = n=1 regardless of sources/books/snapshots)",
          f"  pre-2026-27 matches excluded from the live window: "
          f"{bench['excluded_pre_2026_27_matches']}",
          "  closing lines are COHERENT snapshots: all three outcomes from one "
          "(source, bookmaker, market, captured_at)", ""]
    if not bench["by_source"]:
        L.append("  no admissible pre-kickoff snapshots matched to finished matches yet")
    for source, b in bench["by_source"].items():
        L.append(f"  {source:<20} n={b['n_matches']:<5} "
                 f"source LL {b['source_log_loss']:.4f}  "
                 f"model LL {b['model_log_loss_on_same']:.4f}  "
                 f"delta {b['delta_model_minus_source']:+.4f}")
        v = b["variant"]
        if v:
            L.append(f"      +{v['name']:<16} paired n={v['n_paired']} "
                     f"(coverage {v['coverage']:.0%} — absent twins do NOT reduce "
                     f"the counts above)")
            L.append(f"      {'':<17} variant LL {v['variant_log_loss']:.4f}  "
                     f"vs model {v['delta_variant_minus_model']:+.4f}  "
                     f"vs source {v['delta_variant_minus_source']:+.4f}  "
                     f"(paired subset only)")
        else:
            L.append(f"      +{bench['variant']:<16} no admissible pre-kickoff twin "
                     "paired yet")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit-json", type=Path)
    ap.add_argument("--include-pre-live", action="store_true",
                    help="also count pre-2026-27 matches (provenance only; these "
                         "can NEVER contribute to the q3 confirmation gate)")
    args = ap.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        recon = reconciliation_report(db)
        bench = secondary_market_benchmark(db, live_only=not args.include_pre_live)
    finally:
        db.close()

    print(format_report(recon, bench))
    if args.emit_json:
        args.emit_json.write_text(json.dumps(
            {"reconciliation": recon, "secondary_benchmark": bench},
            indent=2, default=str))
        print(f"\nwrote {args.emit_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
