"""Resolve venue markets to fixtures. DRY-RUN BY DEFAULT; nothing schedules this.

Every subcommand prints what it would do and writes nothing unless ``--apply``
is passed. There is no environment variable that turns writing on, and no
pipeline invokes this module -- it runs when an operator runs it.

Usage::

    # resolve everything, read-only report
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_market_resolution resolve

    # actually write the decisions
    ... resolve --apply

    # operator-supplied structured metadata. Each record asserts venue facts
    # and MUST name its asserter and evidence -- anonymous records fail
    # closed:
    #   {"polymarket": {"0xaaa": {"home_source_key": "arsenal",
    #                             "away_source_key": "chelsea",
    #                             "outcome_source_key": "arsenal",
    #                             "competition_source_key": "premier-league",
    #                             "kickoff_utc": "2026-08-01T16:00:00+00:00",
    #                             "verified_by": "pete",
    #                             "note": "checked the venue event page"}}}
    ... resolve --venue-metadata metadata.json

    # verify one exact source key (the only way keys become trusted)
    ... link-entity --kind team --name "Arsenal" --source kalshi --key ARS \\
        --verified-by "pete" --apply

    # manual correction, audited; the only path that overrides a mapping
    ... correct --venue kalshi --venue-key KXEPLGAME-26AUG01ARSCHE-ARS \\
        --match-id 41 --outcome home --verified-by "pete" \\
        --note "checked the venue listing against the fixture" --apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pipeline.entities.reconcile import (
    apply_correction,
    link_entity,
    reconcile_markets,
)


def _load_metadata(path: Path | None) -> dict[tuple[str, str], dict] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text())
    metadata: dict[tuple[str, str], dict] = {}
    for venue, by_key in raw.items():
        for venue_key, fields in by_key.items():
            metadata[(str(venue), str(venue_key))] = dict(fields)
    return metadata


def _print_report(report) -> None:
    mode = "DRY RUN (pass --apply to write)" if report.dry_run else "APPLIED"
    print(f"{report.resolver_version} — {mode}")
    for outcome in report.outcomes:
        target = ""
        if outcome.match_id is not None:
            target = f" -> match {outcome.match_id} ({outcome.outcome})"
        print(f"  [{outcome.action:>9}] {outcome.venue}:{outcome.venue_key}"
              f"{target}\n              {outcome.reason}")
    # Data gaps are report content the operator must act on -- a fixture that
    # cannot be a candidate names its owed link-entity rows here, instead of
    # every market for it just reading "no fixture shares this pairing".
    if report.data_gaps:
        print(f"data gaps ({len(report.data_gaps)}):")
        for gap in sorted(report.data_gaps):
            print(f"  ! {gap}")
    print("summary:", json.dumps(report.counts()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="resolve all venue markets")
    resolve.add_argument("--apply", action="store_true",
                         help="write decisions; without it nothing changes")
    resolve.add_argument("--venue-metadata", type=Path,
                         help="JSON of operator-supplied structured metadata")

    correct = sub.add_parser("correct", help="audited manual correction")
    correct.add_argument("--venue", required=True)
    correct.add_argument("--venue-key", required=True)
    correct.add_argument("--match-id", type=int)
    correct.add_argument("--outcome", choices=["home", "draw", "away"])
    correct.add_argument("--clear", action="store_true",
                         help="remove the mapping instead of setting one")
    correct.add_argument("--verified-by", required=True)
    correct.add_argument("--note", required=True,
                         help="the evidence for this correction")
    correct.add_argument("--apply", action="store_true")

    link = sub.add_parser("link-entity", help="verify one exact source key")
    link.add_argument("--kind", choices=["team", "competition"], required=True)
    link.add_argument("--name", required=True, help="canonical entity name")
    link.add_argument("--source", required=True,
                      help="'kalshi', 'polymarket', or 'internal'")
    link.add_argument("--key", required=True)
    link.add_argument("--sport", default="football")
    link.add_argument("--verified-by", required=True)
    link.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        if args.command == "resolve":
            report = reconcile_markets(
                db, apply=args.apply,
                metadata_by_key=_load_metadata(args.venue_metadata))
            _print_report(report)
        elif args.command == "correct":
            outcome = apply_correction(
                db, venue=args.venue, venue_key=args.venue_key,
                match_id=args.match_id, outcome=args.outcome,
                clear=args.clear, verified_by=args.verified_by,
                note=args.note, apply=args.apply)
            mode = "APPLIED" if args.apply else "DRY RUN (pass --apply to write)"
            print(f"{mode}: [{outcome.action}] {outcome.venue}:"
                  f"{outcome.venue_key} -> {outcome.match_id} "
                  f"({outcome.outcome}) — {outcome.reason}")
        else:
            message = link_entity(
                db, kind=args.kind, canonical_name=args.name,
                source=args.source, source_key=args.key, sport=args.sport,
                verified_by=args.verified_by, apply=args.apply)
            print(message)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
