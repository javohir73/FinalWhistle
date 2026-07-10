# pipeline/sports/nrl_stats_spike.py
"""MANUAL source spike for NRL team-level match stats (Wave 2, Task 1).

Run by hand; never imported by tests or CI. Probes candidate sources for
team-level match stats + try events, prints what it finds, and (with
--record) saves raw responses into pipeline/sports/testdata/nrl_stats/
as the recorded fixtures every downstream Wave 2 test builds against.

Usage:
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_stats_spike --season 2025 --round 1
    PYTHONPATH=backend:. python -m pipeline.sports.nrl_stats_spike --season 2025 --round 1 --record

Respectful by construction: >= 1s between requests, browser UA, one round.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; NRL-Match-Intel-Spike/1.0; "
                     "contact: pete@degail.com; one-off research probe)"}
TESTDATA = Path(__file__).parent / "testdata" / "nrl_stats"
DRAW_URL = "https://www.nrl.com/draw/data?competition=111&season={season}&round={round_no}"
RLP_SEASON_URL = "https://www.rugbyleagueproject.org/seasons/nrl-{season}/results.html"

_last = 0.0


def _get(url: str) -> requests.Response | None:
    """Rate-limited GET (>= 1s between requests). Returns None on any failure."""
    global _last
    wait = 1.0 - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    try:
        resp = requests.get(url, headers=UA, timeout=20)
        print(f"GET {url} -> {resp.status_code} ({len(resp.content)} bytes)")
        return resp
    except Exception as exc:  # noqa: BLE001 - spike tool, report and move on
        print(f"GET {url} FAILED: {exc}")
        return None


def _extract_qdata(html: str) -> dict | None:
    """Pull the embedded q-data JSON out of an NRL.com match-centre page."""
    m = re.search(r'q-data="([^"]*)"', html)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("&quot;", '"'))
    except ValueError:
        return None


def _walk_titles(obj, depth=0, out=None):
    """Print every dict key path containing stat-ish words, to map field names."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _walk_titles(v, depth + 1, out)
            elif isinstance(k, str) and re.search(
                r"tackle|metre|break|error|penalt|restart|tr(y|ies)|conversion|minute|player",
                k, re.I,
            ):
                out.append(f"{'  ' * depth}{k} = {v!r}")
            if isinstance(v, str) and re.search(
                r"tackle|metre|break|error|penalt|restart|tries|conversion",
                v, re.I,
            ):
                out.append(f"{'  ' * depth}{k}: {v!r}")
    elif isinstance(obj, list):
        for item in obj[:20]:
            _walk_titles(item, depth + 1, out)
    return out


def probe_nrl_com(season: int, round_no: int, record: bool) -> None:
    print("\n=== Candidate 1: NRL.com match centre ===")
    robots = _get("https://www.nrl.com/robots.txt")
    if robots is not None:
        print("--- robots.txt (first 40 lines) ---")
        print("\n".join(robots.text.splitlines()[:40]))

    resp = _get(DRAW_URL.format(season=season, round_no=round_no))
    if resp is None or resp.status_code != 200:
        print("NRL.com draw endpoint: FAIL (criterion 1)")
        return
    try:
        draw = resp.json()
    except ValueError:
        print("NRL.com draw endpoint returned non-JSON: FAIL (criterion 1)")
        return
    fixtures = draw.get("fixtures") or draw.get("drawGroups") or []
    print(f"draw JSON top-level keys: {sorted(draw)[:20]}")
    print(f"fixture-ish entries found: {len(fixtures) if isinstance(fixtures, list) else 'nested'}")
    if record:
        TESTDATA.mkdir(parents=True, exist_ok=True)
        path = TESTDATA / f"draw_{season}_r{round_no:02d}.json"
        path.write_text(json.dumps(draw, indent=2))
        print(f"RECORDED {path}")

    # Probe up to two finished matches for the full stats document.
    flat = fixtures if isinstance(fixtures, list) else []
    recorded = 0
    for fx in flat:
        if not isinstance(fx, dict):
            continue
        url_path = fx.get("matchCentreUrl") or (fx.get("match") or {}).get("matchCentreUrl")
        if not url_path:
            continue
        # Variant A: the JSON data document behind the page.
        data_resp = _get(f"https://www.nrl.com{url_path}data")
        doc = None
        if data_resp is not None and data_resp.status_code == 200:
            try:
                doc = data_resp.json()
                print(f"variant A (…/data JSON) OK for {url_path}")
            except ValueError:
                doc = None
        if doc is None:
            # Variant B: embedded q-data in the HTML page.
            page_resp = _get(f"https://www.nrl.com{url_path}")
            if page_resp is not None and page_resp.status_code == 200:
                doc = _extract_qdata(page_resp.text)
                if doc is not None:
                    print(f"variant B (embedded q-data) OK for {url_path}")
        if doc is None:
            continue
        print("--- stat-ish key paths (criterion 2 checklist) ---")
        print("\n".join(_walk_titles(doc)[:80]))
        if record:
            suffix = "a" if recorded == 0 else "b"
            path = TESTDATA / f"match_{season}_r{round_no:02d}_{suffix}.json"
            path.write_text(json.dumps(doc, indent=2))
            print(f"RECORDED {path}")
        recorded += 1
        if recorded >= 2:
            break
    print(f"NRL.com: recorded {recorded} match documents")


def probe_rugbyleagueproject(season: int) -> None:
    print("\n=== Candidate 2: rugbyleagueproject.org ===")
    robots = _get("https://www.rugbyleagueproject.org/robots.txt")
    if robots is not None:
        print("\n".join(robots.text.splitlines()[:20]))
    resp = _get(RLP_SEASON_URL.format(season=season))
    if resp is None or resp.status_code != 200:
        print("rugbyleagueproject: FAIL (criterion 1)")
        return
    has_stats = bool(re.search(r"run metres|tackle", resp.text, re.I))
    print(f"page fetched; team-level stat fields present: {has_stats} "
          "(expected False -> fails criterion 2 as a sole source)")


def probe_github_datasets() -> None:
    print("\n=== Candidate 3: public GitHub datasets (manual) ===")
    print("Inspect these by hand in a browser (recency >= 2024, per-match team stats, licence):")
    print("  https://github.com/search?q=NRL+match+statistics+dataset&type=repositories")
    print("  https://github.com/search?q=NRL+data+csv+try+scorers&type=repositories")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--round", dest="round_no", type=int, default=1)
    ap.add_argument("--record", action="store_true",
                    help="save raw responses into pipeline/sports/testdata/nrl_stats/")
    args = ap.parse_args()
    probe_nrl_com(args.season, args.round_no, args.record)
    probe_rugbyleagueproject(args.season)
    probe_github_datasets()
    print("\nApply the Task 1 decision procedure to the output above; record the "
          "verdict in pipeline/sports/testdata/nrl_stats/SOURCE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
