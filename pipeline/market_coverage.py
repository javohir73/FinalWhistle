"""D0 — what closing-odds evidence football-data.co.uk actually gives us.

`docs/MODEL-EXPERIMENTS.md` "Finding 1 (P1)" computed the club market baseline
on "~70% of matches [that] carry odds". That figure is the denominator under
every later claim about beating the closing line, and it was never decomposed.
This module decomposes it: per division-season, which 1X2 odds families are
present, how many matches each can actually price, and — crucially — whether
the family a benchmark ends up using is a **closing** line or a pre-closing one.

Three things this module refuses to do, by construction:

- **Impute.** A match with no usable price is excluded and counted, never
  scored against a guessed one. A season file with no closing family is
  abstained from a closing-line benchmark and named, never pooled with seasons
  that have one.
- **Merge bases.** Closing and pre-closing prices are separate series with
  separate labels. They are reported side by side; they are never one column.
- **Re-pin drift.** football-data.co.uk revises published files in place. When
  a capture no longer matches `pipeline/data/club_data_manifest.json` that is a
  finding to record, not a manifest to rewrite.

Odds here are a **benchmark only**. Nothing in this module is importable from a
fit or feature path, and `market_leakage_test.py` asserts it.

Pure and offline apart from :func:`fetch_captures`, which is the one operator-
run network entry point and is never exercised for real by a test.

Usage::

    # operator: fetch the free public CSVs into a gitignored working directory
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.market_coverage \\
        --dir data/raw/club --fetch

    # audit what is there (default scope: the 27 pre-confirmation captures)
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.market_coverage \\
        --dir data/raw/club --emit-json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ml.evaluation.market_benchmark import DEVIG_METHODS, devig
from pipeline.club_data_manifest import (
    DIVISIONS,
    expected_keys,
    load_manifest,
    pre_confirmation_keys,
)
from pipeline.ingest.football_data import (
    DOWNLOAD_URL_TEMPLATE,
    ODDS_FAMILIES,
    PROVIDER,
    OddsFamily,
    available_families,
)

_LABEL_INDEX = {"H": 0, "D": 1, "A": 2}
_EPS = 1e-15

#: Reasons a CSV row cannot become a priced benchmark row. Exhaustive: the
#: counts sum exactly to ``rows`` and a test pins that.
DROP_REASONS = (
    "unparseable_date",
    "missing_or_invalid_score",
    "missing_result",
    "missing_odds",
    "odds_not_above_one",
)


@dataclass(frozen=True)
class FamilyCoverage:
    """How much of one file one odds family can actually price."""

    key: str
    basis: str
    bookmaker: str
    present: bool
    usable: int  # rows with three parseable decimal odds, all > 1.0
    market_log_loss: float | None  # de-vigged, vs realized FTR — market-only


@dataclass(frozen=True)
class FileCensus:
    """One `{DIV}_{SEASON}.csv` capture, described rather than judged."""

    key: str
    rows: int
    columns: int
    sha256: str
    bytes: int
    has_kickoff_time: bool
    families: tuple[FamilyCoverage, ...]
    drops: dict[str, int]
    selected_closing: str | None  # family a closing-only load would pick
    selected_any: str | None  # family a require_basis="any" load would pick

    @property
    def has_closing(self) -> bool:
        return self.selected_closing is not None

    @property
    def abstains(self) -> bool:
        """True when this capture cannot answer a closing-line question."""
        return not self.has_closing


@dataclass(frozen=True)
class DirectoryCensus:
    provider: dict
    scope: str
    keys: tuple[str, ...]
    files: tuple[FileCensus, ...]
    missing: tuple[str, ...]
    manifest_drift: tuple[dict, ...] = field(default=())


def _score_family(
    df: pd.DataFrame, family: OddsFamily | None, method: str
) -> tuple[int, float | None, dict[str, int]]:
    """One pass: how many rows this family can price, its log loss, and why the rest can't.

    "Usable" means *usable as a benchmark row* — parseable date, integer
    scores, a real H/D/A result, and three decimal odds all above 1.0. Those
    are exactly the checks `pipeline.ingest.football_data` applies, so the
    census describes the real loader rather than an idealised one. Anything
    weaker would let a row be counted as covered here and dropped downstream,
    which is how a coverage rate stops meaning anything.

    The market log loss is model-free — the market grading itself — so it is a
    coverage diagnostic that never touches a rating or a fit.

    Returns ``(usable, mean_log_loss, drops)`` where ``usable + sum(drops) ==
    len(df)`` exactly. First failing check wins, in loader order.
    """
    counts = dict.fromkeys(DROP_REASONS, 0)
    cols = family.columns if family else None
    dates = pd.to_datetime(df.get("Date"), dayfirst=True, errors="coerce")
    total, n = 0.0, 0

    for i, row in df.iterrows():
        if pd.isna(dates.iloc[i]):
            counts["unparseable_date"] += 1
            continue
        try:
            int(row["FTHG"]), int(row["FTAG"])
        except (KeyError, TypeError, ValueError):
            counts["missing_or_invalid_score"] += 1
            continue
        label = row.get("FTR")
        if label not in _LABEL_INDEX:
            counts["missing_result"] += 1
            continue
        if cols is None:
            counts["missing_odds"] += 1
            continue
        try:
            o = (float(row[cols[0]]), float(row[cols[1]]), float(row[cols[2]]))
        except (KeyError, TypeError, ValueError):
            counts["missing_odds"] += 1
            continue
        if any(pd.isna(x) for x in o):
            counts["missing_odds"] += 1
            continue
        if min(o) <= 1.0:
            counts["odds_not_above_one"] += 1
            continue
        p = devig(*o, method=method)
        total += -math.log(max(_EPS, p[_LABEL_INDEX[label]]))
        n += 1

    return n, (total / n if n else None), counts


#: Season code of the consumed #202 confirmation holdout. Mirrors
#: `pipeline.club_data_manifest.CONFIRM_SEASON`; a test pins them equal.
_CONFIRMATION_SUFFIX = "_2526"


def _scope_label(keys: list[str]) -> str:
    """Name a scope by what it contains, so an artifact can be read years later.

    ``includes_confirmation`` is the one an auditor cares about: it says a
    burnt-holdout capture was opened, and it says so in the emitted JSON rather
    than only in a stderr warning nobody kept.
    """
    if any(k.endswith(_CONFIRMATION_SUFFIX) for k in keys):
        return "includes_confirmation"
    if set(keys) == set(pre_confirmation_keys()):
        return "pre_confirmation_27"
    return "partial_pre_confirmation"


def census_file(path: Path, devig_method: str = "proportional") -> FileCensus:
    """Describe one capture: families present, what each can price, what drops."""
    raw = path.read_bytes()
    df = pd.read_csv(path, low_memory=False)
    found = available_families(df.columns)
    by_key = {f.key: f for f in found}

    coverage: list[FamilyCoverage] = []
    for fam in ODDS_FAMILIES:
        if fam.key in by_key:
            n, ll, _ = _score_family(df, fam, devig_method)
            coverage.append(
                FamilyCoverage(fam.key, fam.basis, fam.bookmaker, True, n, ll)
            )
        else:
            coverage.append(
                FamilyCoverage(fam.key, fam.basis, fam.bookmaker, False, 0, None)
            )

    closing = next((f for f in found if f.basis == "closing"), None)
    any_fam = found[0] if found else None
    # Drops are attributed against the family a closing-line benchmark would
    # actually use. With no closing family there is nothing to price against,
    # and every row is attributed as missing odds.
    _, _, drops = _score_family(df, closing, devig_method)
    return FileCensus(
        key=path.stem,
        rows=len(df),
        columns=len(df.columns),
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
        # Present from 2019-20 onward; the D1/D4 venue-time joins will need it,
        # and its absence in the early seasons is worth knowing now.
        has_kickoff_time="Time" in df.columns,
        families=tuple(coverage),
        drops=drops,
        selected_closing=closing.key if closing else None,
        selected_any=any_fam.key if any_fam else None,
    )


def census_directory(
    directory: Path,
    keys: list[str] | None = None,
    devig_method: str = "proportional",
    check_manifest: bool = True,
) -> DirectoryCensus:
    """Census every capture in ``keys`` (default: the 27 pre-confirmation ones).

    The default scope deliberately never opens the three ``*_2526`` captures.
    Reading a file's bytes is a holdout read — the distinction T1.6 established
    in `docs/MODEL-EXPERIMENTS.md` — so the confirmation season is out of scope
    unless an operator asks for it and records why.
    """
    scope_keys = list(keys) if keys is not None else pre_confirmation_keys()
    # Derived from the keys, never from HOW they were passed. Labelling by
    # argument shape made the CLI — which always passes an explicit list —
    # stamp every artifact "explicit", so the durable evidence could not say
    # whether the burnt confirmation season had been in scope.
    scope = _scope_label(scope_keys)

    manifest = load_manifest()["files"] if check_manifest else {}
    files: list[FileCensus] = []
    missing: list[str] = []
    drift: list[dict] = []
    for key in scope_keys:
        p = directory / f"{key}.csv"
        if not p.exists():
            missing.append(key)
            continue
        c = census_file(p, devig_method=devig_method)
        files.append(c)
        if manifest and key in manifest and c.sha256 != manifest[key]["sha256"]:
            drift.append(
                {
                    "file": key,
                    "expected_sha256": manifest[key]["sha256"],
                    "actual_sha256": c.sha256,
                    "expected_bytes": manifest[key]["bytes"],
                    "actual_bytes": c.bytes,
                    "expected_rows": manifest[key]["rows"],
                    "actual_rows": c.rows,
                }
            )
    return DirectoryCensus(
        provider=PROVIDER,
        scope=scope,
        keys=tuple(scope_keys),
        files=tuple(files),
        missing=tuple(missing),
        manifest_drift=tuple(drift),
    )


def coverage_summary(census: DirectoryCensus) -> dict:
    """Aggregate the census into the numbers a benchmark must publish.

    Every count carries its denominator. ``closing_any`` is what a
    best-available-closing benchmark could price; ``closing_avgc_only`` is what
    a benchmark pinned to the market-average closing family can price. The gap
    between them is evidence discarded by a column choice, not missing data.
    """
    per_division: dict[str, dict] = {}
    for c in census.files:
        div = c.key.rsplit("_", 1)[0]
        d = per_division.setdefault(
            div,
            {
                "division": div,
                "season_files": 0,
                "rows": 0,
                "closing_any_usable": 0,
                "closing_avgc_usable": 0,
                "abstained_files": [],
                "families_used": {},
            },
        )
        d["season_files"] += 1
        d["rows"] += c.rows
        sel = c.selected_closing
        if sel is None:
            d["abstained_files"].append(c.key)
        else:
            usable = next(f.usable for f in c.families if f.key == sel)
            d["closing_any_usable"] += usable
            d["families_used"][sel] = d["families_used"].get(sel, 0) + 1
        avgc = next((f for f in c.families if f.key == "AvgC"), None)
        if avgc and avgc.present:
            d["closing_avgc_usable"] += avgc.usable

    for d in per_division.values():
        d["coverage_rate_closing_any"] = (
            round(d["closing_any_usable"] / d["rows"], 4) if d["rows"] else None
        )
        d["coverage_rate_closing_avgc"] = (
            round(d["closing_avgc_usable"] / d["rows"], 4) if d["rows"] else None
        )
        d["discarded_by_pinning_avgc"] = (
            d["closing_any_usable"] - d["closing_avgc_usable"]
        )
    return {
        "provider": census.provider,
        "scope": census.scope,
        "n_files": len(census.files),
        "missing_files": list(census.missing),
        "manifest_drift_files": [d["file"] for d in census.manifest_drift],
        "per_division": per_division,
    }


def devig_sensitivity(
    directory: Path, keys: list[str] | None = None
) -> dict[str, dict[str, float | None]]:
    """Market log loss per division under each de-vig method.

    A sensitivity axis, not a selector. It exists so "the model is behind the
    closing line" can be shown not to depend on an arbitrary normalization; no
    method is ever chosen because it flatters the model, and the default in
    :func:`ml.evaluation.market_benchmark.devig` does not move.
    """
    scope_keys = list(keys) if keys is not None else pre_confirmation_keys()
    out: dict[str, dict[str, float | None]] = {}
    for method in DEVIG_METHODS:
        per_div: dict[str, list[tuple[int, float]]] = {}
        for key in scope_keys:
            p = directory / f"{key}.csv"
            if not p.exists():
                continue
            c = census_file(p, devig_method=method)
            if c.selected_closing is None:
                continue
            fam = next(f for f in c.families if f.key == c.selected_closing)
            if fam.market_log_loss is not None:
                per_div.setdefault(key.rsplit("_", 1)[0], []).append(
                    (fam.usable, fam.market_log_loss)
                )
        out[method] = {
            div: (
                round(sum(n * ll for n, ll in vals) / sum(n for n, _ in vals), 4)
                if vals
                else None
            )
            for div, vals in per_div.items()
        }
    return out


def compare_families(census: DirectoryCensus, a: str = "AvgC", b: str = "PSC") -> dict:
    """Are two closing families the same predictor where both are published?

    The question behind swapping a benchmark from one family to another. Only
    captures carrying **both** are compared, so the comparison is paired; the
    captures carrying only one are listed separately as exactly the evidence a
    single-family benchmark discards.
    """
    paired, only_b = [], []
    for c in census.files:
        fam = {f.key: f for f in c.families}
        fa, fb = fam.get(a), fam.get(b)
        if fa and fb and fa.present and fb.present:
            paired.append(
                {
                    "key": c.key,
                    "n": fa.usable,
                    f"{a}_log_loss": fa.market_log_loss,
                    f"{b}_log_loss": fb.market_log_loss,
                    "delta": fb.market_log_loss - fa.market_log_loss,
                }
            )
        elif fb and fb.present and (not fa or not fa.present):
            only_b.append({"key": c.key, "n": fb.usable, "log_loss": fb.market_log_loss})
    deltas = [p["delta"] for p in paired]
    return {
        "family_a": a,
        "family_b": b,
        "paired": paired,
        f"only_{b}": only_b,
        "n_paired_captures": len(paired),
        "max_abs_delta": max((abs(d) for d in deltas), default=None),
        "mean_delta": (sum(deltas) / len(deltas)) if deltas else None,
        f"{b}_better_in": sum(1 for d in deltas if d < 0),
        f"discarded_by_pinning_{a}": sum(o["n"] for o in only_b),
    }


def format_family_comparison(cmp: dict) -> str:
    a, b = cmp["family_a"], cmp["family_b"]
    lines = [
        f"{a} vs {b} on captures where BOTH are present",
        "(mean log loss, vs realized FTR; same rows both columns)",
        "",
        f"{'capture':10s}{'n':>6s}{a + ' LL':>10s}{b + ' LL':>10s}{b + '-' + a:>11s}",
    ]
    for p in cmp["paired"]:
        lines.append(
            f"{p['key']:10s}{p['n']:>6d}{p[f'{a}_log_loss']:>10.4f}"
            f"{p[f'{b}_log_loss']:>10.4f}{p['delta']:>+11.4f}"
        )
    lines += [
        "",
        f"captures with both families: {cmp['n_paired_captures']}",
        f"max |{b} - {a}|           : {cmp['max_abs_delta']:.4f} nats",
        f"mean ({b} - {a})          : {cmp['mean_delta']:+.4f} nats",
        f"{b} better in             : {cmp[f'{b}_better_in']}/{cmp['n_paired_captures']} captures",
        "",
        f"{b}-only captures (no {a}) — the evidence an {a}-pinned benchmark discards:",
    ]
    for o in cmp[f"only_{b}"]:
        lines.append(f"  {o['key']:10s} n={o['n']:>4d}  {b} LL={o['log_loss']:.4f}")
    lines.append(f"  total discarded: {cmp[f'discarded_by_pinning_{a}']} matches")
    return "\n".join(lines)


def join_diagnostics(
    model_keys: list[tuple], odds_keys: list[tuple]
) -> dict:
    """Attribute every model row that failed to find a price.

    ``model_keys`` / ``odds_keys`` are ``(date, home, away)`` tuples. The join
    is **exact**, with the orientation swap the benchmark already permits and
    nothing else — no nearest-date, no fuzzy name match. A near-miss must show
    up here as a miss, because silently absorbing it is how a leak gets in.
    """
    odds = set(odds_keys)
    swapped = {(d, a, h) for (d, h, a) in odds_keys}
    matched = matched_swapped = 0
    unmatched_same_day: list[tuple] = []
    unmatched: list[tuple] = []
    same_day = {(d, h) for (d, h, _) in odds_keys} | {(d, a) for (d, _, a) in odds_keys}
    for k in model_keys:
        if k in odds:
            matched += 1
        elif k in swapped:
            matched_swapped += 1
        elif (k[0], k[1]) in same_day or (k[0], k[2]) in same_day:
            # A club played that day but this pairing has no price: an
            # orientation or naming problem, not an absent fixture.
            unmatched_same_day.append(k)
        else:
            unmatched.append(k)
    n = len(model_keys)
    return {
        "n_eligible": n,
        "n_matched": matched + matched_swapped,
        "n_matched_orientation_swapped": matched_swapped,
        "coverage_rate": round((matched + matched_swapped) / n, 4) if n else None,
        "drops": {
            "same_day_pairing_absent": len(unmatched_same_day),
            "fixture_absent": len(unmatched),
        },
        "unmatched_same_day_sample": unmatched_same_day[:20],
    }


class ConfirmationFetchRefused(RuntimeError):
    """Refused to download a confirmation-season capture."""


def fetch_captures(
    directory: Path,
    keys: list[str] | None = None,
    delay_s: float = 0.4,
    allow_confirmation: bool = False,
) -> list[str]:
    """Download the free public CSVs for ``keys`` into ``directory``.

    The one network entry point in this module, and operator-run only: no test
    calls it for real, nothing schedules it, it costs nothing and needs no key.
    Existing files are left alone — re-fetching would overwrite the very bytes
    a drift check is about to compare.

    **Refuses to fetch a confirmation-season capture unless asked twice.**
    Widening the census scope is a decision about what to *read*; downloading is
    a decision to put the burnt holdout on disk, where the next default-scope
    run will not touch it but the next careless glob will. Those are different
    decisions and they need different flags.
    """
    directory.mkdir(parents=True, exist_ok=True)
    scope = list(keys) if keys is not None else pre_confirmation_keys()
    held_out = [k for k in scope if k.endswith(_CONFIRMATION_SUFFIX)]
    if held_out and not allow_confirmation:
        raise ConfirmationFetchRefused(
            "refusing to download confirmation-season captures "
            f"{sorted(held_out)}: the 2025-26 season is the consumed #202 "
            "holdout. Pass allow_confirmation=True (CLI: --fetch-confirmation) "
            "only for a #202 reproduction, and record the reason."
        )
    written: list[str] = []
    for key in scope:
        division, season = key.rsplit("_", 1)
        dest = directory / f"{key}.csv"
        if dest.exists():
            continue
        url = DOWNLOAD_URL_TEMPLATE.format(season=season, division=division)
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (fixed https host)
            dest.write_bytes(resp.read())
        written.append(key)
        time.sleep(delay_s)
    return written


def format_report(census: DirectoryCensus, summary: dict) -> str:
    lines = [
        "=== D0 closing-odds coverage census ===",
        f"provider : {census.provider['provider']}  ({census.provider['cost']})",
        f"licence  : {census.provider['licence']}",
        f"scope    : {census.scope}  ({len(census.files)} captures)",
        "",
        f"{'capture':10s}{'rows':>6s}{'cols':>6s}{'closing':>9s}{'usable':>8s}"
        f"{'AvgC':>7s}{'PSC':>7s}{'Time':>6s}",
    ]
    for c in census.files:
        sel = c.selected_closing or "NONE"
        usable = (
            next(f.usable for f in c.families if f.key == sel) if c.selected_closing else 0
        )
        avgc = next(f for f in c.families if f.key == "AvgC")
        psc = next(f for f in c.families if f.key == "PSC")
        lines.append(
            f"{c.key:10s}{c.rows:>6d}{c.columns:>6d}{sel:>9s}{usable:>8d}"
            f"{('y' if avgc.present else '-'):>7s}{('y' if psc.present else '-'):>7s}"
            f"{('y' if c.has_kickoff_time else '-'):>6s}"
        )
    lines += ["", "per division (denominators always shown):"]
    for div in DIVISIONS:
        d = summary["per_division"].get(div)
        if not d:
            continue
        lines.append(
            f"  {div:4s} rows={d['rows']:>5d}  "
            f"closing(any)={d['closing_any_usable']:>5d} "
            f"({d['coverage_rate_closing_any']:.1%})  "
            f"closing(AvgC only)={d['closing_avgc_usable']:>5d} "
            f"({d['coverage_rate_closing_avgc']:.1%})  "
            f"discarded by pinning AvgC={d['discarded_by_pinning_avgc']:>5d}"
        )
        if d["abstained_files"]:
            lines.append(f"       ABSTAINED (no closing family): {d['abstained_files']}")
    if census.missing:
        lines.append(f"\nMISSING captures: {list(census.missing)}")
    if census.manifest_drift:
        # Deliberately does NOT assert the publisher revised anything. The only
        # input to this branch is a sha256 mismatch, which a local edit, a
        # truncated download or a different capture method produces just as
        # readily. Naming a cause the evidence cannot support is the same error
        # this phase exists to correct.
        lines.append(
            f"\nMANIFEST DRIFT on {len(census.manifest_drift)} capture(s): these "
            "bytes are not the recorded capture. Cause is NOT established here — "
            "the publisher is known to revise files in place, but a local edit or "
            "a partial download looks identical to a hash. Recorded, NOT re-pinned:"
        )
        for d in census.manifest_drift:
            lines.append(
                f"  {d['file']:10s} bytes {d['expected_bytes']} -> {d['actual_bytes']}"
                f"  rows {d['expected_rows']} -> {d['actual_rows']}"
            )
    return "\n".join(lines)


def _to_json(census: DirectoryCensus, summary: dict, sensitivity: dict | None) -> dict:
    return {
        "provider": census.provider,
        "scope": census.scope,
        "keys": list(census.keys),
        "missing": list(census.missing),
        "manifest_drift": [dict(d) for d in census.manifest_drift],
        "files": [
            {
                "key": c.key,
                "rows": c.rows,
                "columns": c.columns,
                "sha256": c.sha256,
                "bytes": c.bytes,
                "has_kickoff_time": c.has_kickoff_time,
                "selected_closing": c.selected_closing,
                "selected_any": c.selected_any,
                "abstains": c.abstains,
                "drops": c.drops,
                "families": [
                    {
                        "key": f.key,
                        "basis": f.basis,
                        "bookmaker": f.bookmaker,
                        "present": f.present,
                        "usable": f.usable,
                        "market_log_loss": (
                            round(f.market_log_loss, 6)
                            if f.market_log_loss is not None
                            else None
                        ),
                    }
                    for f in c.families
                ],
            }
            for c in census.files
        ],
        "summary": summary,
        "devig_sensitivity": sensitivity,
    }


def build_parser() -> argparse.ArgumentParser:
    """The CLI's arguments. Split out of main() so the capture-directory
    resolution (stop gate G1) is testable without invoking a run."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # Stop gate G1 (docs/DATA-VALIDATION-PROGRAM.md, decided 2026-08-07): the
    # football-data.co.uk captures are licensed for download but NOT for
    # redistribution, and this repository is public — so they are retained in
    # private storage outside the checkout. Honouring CLUB_CAPTURE_DIR here
    # means an operator who forgets the flag lands in that private store rather
    # than silently re-populating the in-repo working directory. The old
    # default stays for anyone with nothing configured; .gitignore covers it.
    ap.add_argument(
        "--dir",
        default=os.environ.get("CLUB_CAPTURE_DIR") or "data/raw/club",
        help="capture directory (default: $CLUB_CAPTURE_DIR, else data/raw/club)",
    )
    ap.add_argument(
        "--fetch",
        action="store_true",
        help="download missing captures first (free public CSVs, no key)",
    )
    ap.add_argument(
        "--include-confirmation",
        action="store_true",
        help="widen scope to all 30 captures. Opening a *_2526 capture is a "
        "holdout READ — only for a #202 reproduction, and record why.",
    )
    ap.add_argument("--devig", default="proportional", choices=DEVIG_METHODS)
    ap.add_argument(
        "--fetch-confirmation",
        action="store_true",
        help="permit --fetch to download the *_2526 holdout captures. Separate "
        "from --include-confirmation on purpose: reading and downloading the "
        "burnt holdout are different decisions.",
    )
    ap.add_argument(
        "--sensitivity",
        action="store_true",
        help="also report market log loss under every de-vig method",
    )
    ap.add_argument(
        "--compare-families",
        nargs=2,
        metavar=("A", "B"),
        help="paired per-capture comparison of two odds families, e.g. AvgC PSC",
    )
    ap.add_argument("--emit-json", help="write the full census to this path")
    ap.add_argument("--emit-comparison", help="write --compare-families to this path")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    directory = Path(args.dir)
    keys = expected_keys() if args.include_confirmation else pre_confirmation_keys()
    if args.include_confirmation:
        print(
            "WARNING: confirmation-season captures are in scope. Opening them is "
            "a holdout read — record the reason in the evidence card.",
            file=sys.stderr,
        )

    if args.fetch:
        written = fetch_captures(
            directory, keys, allow_confirmation=args.fetch_confirmation
        )
        print(f"fetched {len(written)} capture(s): {written}", file=sys.stderr)

    census = census_directory(directory, keys=keys, devig_method=args.devig)
    summary = coverage_summary(census)
    sensitivity = devig_sensitivity(directory, keys=keys) if args.sensitivity else None

    print(format_report(census, summary))
    if sensitivity:
        print("\nde-vig sensitivity (market log loss, closing family, weighted):")
        for method, per_div in sensitivity.items():
            row = "  ".join(
                f"{d}={v:.4f}" for d, v in sorted(per_div.items()) if v is not None
            )
            print(f"  {method:14s}{row}")

    if args.compare_families:
        cmp = compare_families(census, *args.compare_families)
        text = format_family_comparison(cmp)
        if args.emit_comparison:
            Path(args.emit_comparison).write_text(text + "\n")
            print(f"wrote {args.emit_comparison}", file=sys.stderr)
        else:
            print("\n" + text)

    if args.emit_json:
        Path(args.emit_json).write_text(
            json.dumps(_to_json(census, summary, sensitivity), indent=2)
        )
        print(f"\nwrote {args.emit_json}", file=sys.stderr)

    # Non-zero on anything that makes a published number untrustworthy: a
    # capture that cannot answer a closing-line question, a capture that is not
    # there, or a capture whose bytes are not the recorded ones. Drift belongs
    # in this list — `pipeline.club_data_manifest` already exits 1 on it, and
    # two tools disagreeing about whether 27/27 drift is an error is worse than
    # either answer.
    if any(c.abstains for c in census.files) or census.missing or census.manifest_drift:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
