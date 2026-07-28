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


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or MANIFEST_PATH).read_text())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_keys() -> list[str]:
    return [f"{d}_{s}" for d in DIVISIONS for s in SEASONS]


def verify(directory: Path, manifest: dict | None = None) -> dict:
    """Compare ``directory``'s {DIV}_{SEASON}.csv captures against the manifest.

    Returns counts plus the per-file verdicts. ``drifted`` means the upstream
    publisher changed a file that a recorded experiment was fitted on — the
    result in the ledger is then no longer reproducible from live downloads,
    and that is worth knowing explicitly.
    """
    man = manifest or load_manifest()
    files = man["files"]
    matched, drifted, missing = [], [], []
    for key in expected_keys():
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
        "matched": len(matched),
        "drifted": drifted,
        "missing": missing,
        "reproducible": not drifted and not missing,
    }


def format_report(result: dict) -> str:
    lines = [
        f"manifest files : {result['manifest_files']}",
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
    args = ap.parse_args()
    result = verify(args.dir)
    print(format_report(result))
    return 0 if result["reproducible"] else 1


if __name__ == "__main__":
    sys.exit(main())
