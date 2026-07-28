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


def reconciliation_report(db) -> dict:
    """Unmatched observations and score disagreements, per source."""
    per_source: dict[str, dict] = defaultdict(
        lambda: {"observations": 0, "matched": 0, "unmatched": 0, "conflict": 0,
                 "score_agreements": 0, "score_disagreements": 0})
    unmatched_examples: list[dict] = []
    disagreements: list[dict] = []

    for obs in db.query(ValidationFixtureObservation).all():
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
            "unmatched_examples": unmatched_examples,
            "score_disagreements": disagreements,
            "clean": not disagreements and not unmatched_examples}


def _closing_by_source(db, match: Match) -> dict[str, dict[str, float]]:
    """Latest admissible pre-kickoff de-vigged 1X2, PER SOURCE.

    Never merged across sources. `captured_at` is the source's own timestamp;
    a snapshot at or after kickoff is inadmissible and dropped.
    """
    if match.kickoff_utc is None:
        return {}
    kickoff = _aware(match.kickoff_utc)
    best: dict[tuple[str, str], ValidationMarketSnapshot] = {}
    rows = (db.query(ValidationMarketSnapshot)
            .filter(ValidationMarketSnapshot.match_id == match.id).all())
    for r in rows:
        captured = _aware(r.captured_at)
        if captured is None or captured >= kickoff:
            continue  # at or after kickoff is inadmissible, never clamped
        if r.implied_prob_devig is None:
            continue
        key = (r.source, r.bookmaker_key)
        cur = best.get((key[0], key[1] + "|" + r.outcome))
        if cur is None or captured > _aware(cur.captured_at):
            best[(key[0], key[1] + "|" + r.outcome)] = r

    grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for (source, bk_outcome), r in best.items():
        grouped[source][bk_outcome.split("|")[0]].append(r)

    out: dict[str, dict[str, float]] = {}
    for source, books in grouped.items():
        # One book per source: the latest-captured complete 1X2 triple.
        for _bk, rows_ in sorted(books.items()):
            triple = {r.outcome: r.implied_prob_devig for r in rows_}
            if set(triple) == {"home", "draw", "away"}:
                total = sum(triple.values())
                if total > 0:
                    out[source] = {k: v / total for k, v in triple.items()}
                break
    return out


def secondary_market_benchmark(db, *, live_only: bool = True) -> dict:
    """Per-source closing benchmark vs our frozen production predictions."""
    per_source: dict[str, dict] = defaultdict(
        lambda: {"n_matches": 0, "source_ll": 0.0, "model_ll": 0.0})
    match_ids: set[int] = set()
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
        for source, probs in _closing_by_source(db, m).items():
            s = per_source[source]
            s["n_matches"] += 1
            ordered = (probs["home"], probs["draw"], probs["away"])
            s["source_ll"] += -math.log(max(ordered[label], _EPS))
            s["model_ll"] += -math.log(max(model[label], _EPS))
            match_ids.add(m.id)

    out = {}
    for source, s in sorted(per_source.items()):
        n = s["n_matches"]
        out[source] = {
            "n_matches": n,
            "source_log_loss": s["source_ll"] / n,
            "model_log_loss_on_same": s["model_ll"] / n,
            "delta_model_minus_source": (s["model_ll"] - s["source_ll"]) / n,
        }
    return {
        "status": "SECONDARY — does not replace the pre-registered "
                  "API-Football baseline in run_calibrator_benchmark.py",
        "live_only": live_only,
        "excluded_pre_2026_27_matches": excluded_pre_live,
        "distinct_matches": len(match_ids),
        "by_source": out,
    }


def format_report(recon: dict, bench: dict) -> str:
    L = ["Independent validation sources — reconciliation", ""]
    if not recon["per_source"]:
        L.append("  no observations ingested yet (sources are default OFF)")
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
          f"{bench['excluded_pre_2026_27_matches']}", ""]
    if not bench["by_source"]:
        L.append("  no admissible pre-kickoff snapshots matched to finished matches yet")
    for source, b in bench["by_source"].items():
        L.append(f"  {source:<20} n={b['n_matches']:<5} "
                 f"source LL {b['source_log_loss']:.4f}  "
                 f"model LL {b['model_log_loss_on_same']:.4f}  "
                 f"delta {b['delta_model_minus_source']:+.4f}")
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
