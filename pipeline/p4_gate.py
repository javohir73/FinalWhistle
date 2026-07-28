"""Mechanical P4 classification and branch selection from a frozen P3 result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def classify_group(group: dict) -> str:
    if group.get("status") != "ready" or not group.get("diff_ci95"):
        return "insufficient"
    low, high = map(float, group["diff_ci95"])
    if high < 0:
        return "beating"
    if low > 0:
        return "beaten"
    return "inconclusive"


def select_branch(result: dict, *, venue: str, market_type: str, horizon: str) -> dict:
    matches = [
        group for group in result.get("groups", [])
        if group.get("venue") == venue and group.get("market_type") == market_type and group.get("horizon") == horizon
    ]
    if len(matches) != 1:
        return {"verdict": "insufficient", "selected_branch": None, "reason": "precommitted comparison group missing or non-unique"}
    verdict = classify_group(matches[0])
    branch = "P5B" if verdict == "beating" else ("P5A" if verdict in {"beaten", "inconclusive"} else None)
    reasons = {
        "beating": "CI95 entirely below zero",
        "beaten": "CI95 entirely above zero",
        "inconclusive": "CI95 touches or crosses zero",
        "insufficient": "no sufficient held-out comparison",
    }
    return {
        "verdict": verdict,
        "selected_branch": branch,
        "reason": reasons[verdict],
        "claim": {"venue": venue, "market_type": market_type, "horizon": horizon},
        "group": matches[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--market-type", required=True)
    parser.add_argument("--horizon", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    decision = select_branch(json.loads(args.results.read_text()), venue=args.venue, market_type=args.market_type, horizon=args.horizon)
    body = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(body)
    print(body, end="")
    return 0 if decision["selected_branch"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
