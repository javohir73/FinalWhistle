"""Phase-0 depth probe: how much club xG can API-Football actually give us?

Prints per (league, season) the fixture count and how many carry a non-null
`expected_goals` statistic, then applies the PRE-REGISTERED gate from the plan
(>=3000 covered matches across >=6 league-seasons). Diagnostic only: no writes,
never raises. Usage:
    PYTHONPATH=backend:. .venv/bin/python -m pipeline.probe_club_xg --api-key $KEY
"""
from __future__ import annotations
import argparse, sys, requests

BASE = "https://v3.football.api-sports.io"
# API-Football league ids for the top-5 European leagues.
LEAGUES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
SEASONS = [2018, 2019, 2020, 2021, 2022, 2023]
GATE_MATCHES, GATE_CELLS = 3000, 6

def _get(path, key, params):
    try:
        r = requests.get(f"{BASE}{path}", headers={"x-apisports-key": key}, params=params, timeout=20)
        return r.json().get("response") or []
    except Exception as exc:  # noqa: BLE001 - diagnostic must never raise
        print(f"  ! {path} {params}: {exc}", file=sys.stderr)
        return []

def _has_xg(fixture_id, key) -> bool:
    for block in _get("/fixtures/statistics", key, {"fixture": fixture_id}):
        for s in block.get("statistics") or []:
            if s.get("type") == "expected_goals" and s.get("value") not in (None, ""):
                return True
    return False

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--api-key", required=True)
    ap.add_argument("--sample", type=int, default=20, help="fixtures/cell to probe for xG")
    args = ap.parse_args()
    total_covered, cells_with_xg = 0, 0
    for lid, lname in LEAGUES.items():
        for season in SEASONS:
            fx = _get("/fixtures", args.api_key, {"league": lid, "season": season})
            done = [f for f in fx if ((f.get("fixture") or {}).get("status") or {}).get("short") == "FT"]
            sample = done[: args.sample]
            covered = sum(_has_xg((f.get("fixture") or {}).get("id"), args.api_key) for f in sample)
            frac = covered / len(sample) if sample else 0.0
            est = int(round(frac * len(done)))
            if covered:
                cells_with_xg += 1
                total_covered += est
            print(f"{lname} {season}: {len(done)} FT, xG in {covered}/{len(sample)} sampled -> ~{est} covered")
    ok = total_covered >= GATE_MATCHES and cells_with_xg >= GATE_CELLS
    print(f"\nESTIMATE: ~{total_covered} covered matches across {cells_with_xg} league-seasons")
    print(f"GATE (>= {GATE_MATCHES} matches AND >= {GATE_CELLS} cells): {'GO' if ok else 'STOP -> escalate Understat fallback'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
