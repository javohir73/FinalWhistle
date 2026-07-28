"""Pin the raw club CSVs the model program was fitted on.

football-data.co.uk revises published season files IN PLACE. Every club gate in
`docs/MODEL-EXPERIMENTS.md` downloaded them live, so re-running the program
later could silently score against different bytes and produce different
"reproductions" of a recorded result — with nothing in the output to say the
inputs moved.

`pipeline/data/club_data_manifest.json` records sha256/size/row-count for the
30 season files (E0/SP1/D1 x 2016-17..2025-26) captured 2026-07-28, the state
the shipped params were fitted on. `verify()` compares a directory of captures
against it and reports drift instead of failing silently.

This does NOT re-pin on drift. A changed upstream file is a finding to
investigate and record in the ledger, never something to paper over.

Usage::

    PYTHONPATH=backend:. .venv/bin/python -m pipeline.club_data_manifest --dir data/raw/club
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent / "data" / "club_data_manifest.json"
DIVISIONS = ("E0", "SP1", "D1")
SEASONS = ("1617", "1718", "1819", "1920", "2021",
           "2122", "2223", "2324", "2425", "2526")

#: The season the #202 confirmation run consumed. Mirrors
#: ml.evaluation.club_calibration.CONFIRM_SEASON and
#: pipeline.ingest.club_results.HOLDOUT_SEASON_CODE — a consistency test pins
#: all three together rather than having a data module import an evaluation one.
CONFIRM_SEASON = "2526"

#: The nine seasons a post-confirmation experiment may legitimately touch.
PRE_CONFIRMATION_SEASONS = tuple(s for s in SEASONS if s != CONFIRM_SEASON)


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or MANIFEST_PATH).read_text())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_keys(seasons: tuple[str, ...] = SEASONS) -> list[str]:
    """Manifest keys for ``seasons`` (all ten by default)."""
    return [f"{d}_{s}" for d in DIVISIONS for s in seasons]


def pre_confirmation_keys() -> list[str]:
    """The 27 keys a post-confirmation experiment may verify.

    Verification HASHES files, which means opening and reading them. For an
    experiment that must not read the consumed holdout at all, verifying the
    full 30-file set would itself be a holdout read — before any season filter
    downstream ever runs. T1.6 therefore verifies this subset, and the three
    ``*_2526`` captures are never opened.
    """
    return expected_keys(PRE_CONFIRMATION_SEASONS)


def verify(directory: Path, manifest: dict | None = None,
           keys: list[str] | None = None) -> dict:
    """Compare ``directory``'s {DIV}_{SEASON}.csv captures against the manifest.

    ``keys`` restricts which captures are opened; None means all 30 (the #202
    reproduction scope). Files outside ``keys`` are neither opened nor hashed
    nor stat-ed — that is the property T1.6 depends on, so it is asserted by a
    test that poisons the excluded files.

    Returns counts plus the per-file verdicts. ``drifted`` means the upstream
    publisher changed a file that a recorded experiment was fitted on — the
    result in the ledger is then no longer reproducible from live downloads,
    and that is worth knowing explicitly.
    """
    man = manifest or load_manifest()
    files = man["files"]
    scope = list(keys) if keys is not None else expected_keys()
    unknown = [k for k in scope if k not in files]
    if unknown:
        raise KeyError(f"keys absent from the manifest: {sorted(unknown)}")
    matched, drifted, missing = [], [], []
    for key in scope:
        p = directory / f"{key}.csv"
        if not p.exists():
            missing.append(key)
            continue
        actual = sha256_of(p)
        if actual == files[key]["sha256"]:
            matched.append(key)
        else:
            drifted.append({"file": key, "expected": files[key]["sha256"],
                            "actual": actual})
    return {
        "manifest_files": len(files),
        "expected": len(scope),
        "scope": scope,
        "matched": len(matched),
        "drifted": drifted,
        "missing": missing,
        "reproducible": not drifted and not missing,
    }


def format_report(result: dict) -> str:
    lines = [
        f"manifest files : {result['manifest_files']}",
        f"verified scope : {result['expected']} files",
        f"matched        : {result['matched']}",
        f"drifted        : {len(result['drifted'])}",
        f"missing        : {len(result['missing'])}",
    ]
    for d in result["drifted"]:
        lines.append(f"  DRIFT {d['file']}: expected {d['expected'][:16]}… "
                     f"got {d['actual'][:16]}…")
    if result["missing"]:
        lines.append(f"  MISSING {', '.join(result['missing'][:8])}"
                     + ("…" if len(result["missing"]) > 8 else ""))
    lines.append("")
    lines.append("REPRODUCIBLE — inputs match what the shipped params were fitted on"
                 if result["reproducible"] else
                 "NOT REPRODUCIBLE against the recorded capture; investigate before "
                 "citing any ledger number as reproduced")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path, required=True,
                    help="directory of {DIV}_{SEASON}.csv captures to verify")
    ap.add_argument("--pre-confirmation-only", action="store_true",
                    help=f"verify the 27 pre-confirmation captures only, leaving "
                         f"the {CONFIRM_SEASON} holdout unopened")
    args = ap.parse_args()
    result = verify(args.dir,
                    keys=pre_confirmation_keys() if args.pre_confirmation_only else None)
    print(format_report(result))
    return 0 if result["reproducible"] else 1


if __name__ == "__main__":
    sys.exit(main())
