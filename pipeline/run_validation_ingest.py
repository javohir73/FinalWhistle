"""Ingest independent validation sources. DEFAULT OFF, isolated, best-effort.

Selection is by explicit flag only -- there is no "all sources" default and no
env var that turns everything on at once. Each source runs inside its own
boundary: unconfigured, timed out, rate limited or malformed yields an empty
result and a recorded reason, and can never affect production or shadow writes
because it shares no code path with them.

Betfair is IMPORTER ONLY. It reads an archive the operator downloaded, requires
both the file digest and an acquisition note, and never authenticates or
fetches.

Usage::

    # free, no key
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_validation_ingest \\
        --source openligadb --season 2026

    # needs FOOTBALL_DATA_API_KEY / ODDS_API_KEY in the environment
    ... --source football_data_org --season 2026
    ... --source the_odds_api

    # offline import of a file YOU downloaded
    ... --source betfair_historical --archive /path/to/file.jsonl \\
        --acquisition-note "downloaded 2026-09-01, Betfair historical PRO tier" \\
        --competition-id <betfair Bundesliga competitionId>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.ingest.validation import loader, sources

SOURCES = ("football_data_org", "openligadb", "the_odds_api", "betfair_historical")


def run_source(db, source: str, *, season: int | None = None,
               archive: Path | None = None, acquisition_note: str | None = None,
               competition_id: str | None = None, requests_mod=None) -> dict:
    """Run ONE source. Never raises for a source-side problem."""
    if source == "openligadb":
        res = sources.fetch_openligadb(season, requests_mod=requests_mod)
        return {"source": source, "ok": res.ok, "reason": res.reason,
                **(loader.load_fixture_observations(db, res.items) if res.ok else {})}

    if source == "football_data_org":
        res = sources.fetch_football_data_org(season, requests_mod=requests_mod)
        return {"source": source, "ok": res.ok, "reason": res.reason,
                **(loader.load_fixture_observations(db, res.items) if res.ok else {})}

    if source == "the_odds_api":
        res = sources.fetch_odds_api(requests_mod=requests_mod)
        return {"source": source, "ok": res.ok, "reason": res.reason,
                **(loader.load_market_observations(db, res.items) if res.ok else {})}

    if source == "betfair_historical":
        if archive is None or not acquisition_note:
            return {"source": source, "ok": False,
                    "reason": "betfair import requires --archive AND "
                              "--acquisition-note (importer-only provenance)"}
        if not competition_id:
            return {"source": source, "ok": False,
                    "reason": "betfair import requires --competition-id: the "
                              "archive's competition is validated against it, "
                              "never assumed"}
        try:
            digest = sources.file_sha256(archive)
            with open(archive, encoding="utf-8") as fh:
                items = sources.parse_betfair_archive(
                    fh, archive_sha256=digest, acquisition_note=acquisition_note,
                    competition_id=competition_id)
        except Exception as exc:  # noqa: BLE001 - a bad file must not propagate
            return {"source": source, "ok": False,
                    "reason": f"{type(exc).__name__}: {exc}"}
        return {"source": source, "ok": True, "archive_sha256": digest,
                **loader.load_market_observations(db, items)}

    return {"source": source, "ok": False, "reason": f"unknown source {source!r}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, choices=SOURCES,
                    help="exactly one source; there is no all-sources default")
    ap.add_argument("--season", type=int)
    ap.add_argument("--archive", type=Path, help="betfair_historical only")
    ap.add_argument("--acquisition-note", help="betfair_historical only; required")
    ap.add_argument("--competition-id",
                    help="betfair_historical only; required. Betfair competitionId "
                         "for Bundesliga, validated against the archive metadata")
    ap.add_argument("--emit-json", type=Path)
    args = ap.parse_args()

    if args.source in ("openligadb", "football_data_org") and args.season is None:
        ap.error(f"--season is required for {args.source}")

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        result = run_source(db, args.source, season=args.season,
                            archive=args.archive,
                            acquisition_note=args.acquisition_note,
                            competition_id=args.competition_id)
    finally:
        db.close()

    print(json.dumps(result, indent=2, default=str))
    if args.emit_json:
        args.emit_json.write_text(json.dumps(result, indent=2, default=str))
    # A source-side problem is reported, not a process failure: these runs are
    # advisory and must never fail a pipeline they are attached to.
    return 0


if __name__ == "__main__":
    sys.exit(main())
