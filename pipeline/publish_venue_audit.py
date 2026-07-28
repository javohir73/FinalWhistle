"""Regenerate the public WC26 venue-calibration audit from frozen inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
DEFAULT_INPUT = (
    ROOT
    / "docs/experiments/2026-07-23-wc26-postmortem/exchange-prices-n104.json"
)
DEFAULT_OUTPUT = ROOT / "frontend/lib/venue-audit-data.json"

# The original experiment did not record its bootstrap seed. These intervals
# are therefore frozen evidence values, while every point metric below is
# recomputed from the committed match-level probabilities. P3 fixes this
# provenance gap by requiring a seed before the run.
FROZEN_CI95 = {
    "kalshi": [0.0173, 0.1105],
    "polymarket": [-0.0059, 0.0878],
}
BOOTSTRAP_SEED = 20260727
BOOTSTRAP_SAMPLES = 10_000


def _probs(value: Any) -> tuple[float, float, float]:
    if isinstance(value, list) and len(value) == 3:
        values = [float(item) for item in value]
    elif isinstance(value, dict):
        values = [float(value[key]) for key in ("home", "draw", "away")]
    else:
        raise ValueError("probability row must contain home/draw/away")
    total = sum(values)
    if total <= 0 or any(item < 0 for item in values):
        raise ValueError("probabilities must be non-negative with positive sum")
    return tuple(item / total for item in values)


def _label(match: dict[str, Any]) -> int:
    if match["h90"] > match["a90"]:
        return 0
    if match["h90"] < match["a90"]:
        return 2
    return 1


def _metrics(rows: list[tuple[tuple[float, ...], int]]) -> dict[str, float]:
    n = len(rows)
    return {
        "favorite_hit_rate": sum(
            max(range(3), key=lambda index: probs[index]) == label
            for probs, label in rows
        )
        / n,
        "log_loss": sum(-math.log(max(probs[label], 1e-15)) for probs, label in rows)
        / n,
        "brier": sum(
            sum((probs[index] - (index == label)) ** 2 for index in range(3))
            for probs, label in rows
        )
        / n,
    }


def _paired_ci95(
    model_rows: list[tuple[tuple[float, ...], int]],
    venue_rows: list[tuple[tuple[float, ...], int]],
) -> list[float]:
    diffs = [
        -math.log(max(model[label], 1e-15)) + math.log(max(venue[label], 1e-15))
        for (model, label), (venue, venue_label) in zip(model_rows, venue_rows)
        if label == venue_label
    ]
    rng = random.Random(BOOTSTRAP_SEED)
    count = len(diffs)
    draws = sorted(
        sum(diffs[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return [draws[int(.025 * BOOTSTRAP_SAMPLES)], draws[int(.975 * BOOTSTRAP_SAMPLES)]]


def build_audit(source: dict[str, Any], *, input_sha256: str) -> dict[str, Any]:
    matches = source["matches"]
    by_id = {str(match["id"]): match for match in matches}
    venues: dict[str, Any] = {}
    for venue in ("kalshi", "polymarket"):
        keys = [key for key in by_id if key in source[venue]]
        model_rows = [(_probs(source["model"][key]), _label(by_id[key])) for key in keys]
        venue_rows = [(_probs(source[venue][key]), _label(by_id[key])) for key in keys]
        model_metrics = _metrics(model_rows)
        venue_metrics = _metrics(venue_rows)
        venues[venue] = {
            "n_matches": len(keys),
            "model": model_metrics,
            "venue": venue_metrics,
            "diff_log_loss": model_metrics["log_loss"] - venue_metrics["log_loss"],
            "diff_ci95": FROZEN_CI95[venue],
            "recomputed_diff_ci95": _paired_ci95(model_rows, venue_rows),
            "verdict": (
                "beaten"
                if FROZEN_CI95[venue][0] > 0
                else "inconclusive"
            ),
        }

    overlap = [
        key for key in by_id if key in source["kalshi"] and key in source["polymarket"]
    ]
    divergences: list[float] = []
    favorite_disagreements = 0
    consensus_rows = []
    kalshi_overlap_rows = []
    polymarket_overlap_rows = []
    model_overlap_rows = []
    for key in overlap:
        label = _label(by_id[key])
        kalshi = _probs(source["kalshi"][key])
        polymarket = _probs(source["polymarket"][key])
        divergences.append(max(abs(a - b) for a, b in zip(kalshi, polymarket)))
        favorite_disagreements += max(range(3), key=kalshi.__getitem__) != max(
            range(3), key=polymarket.__getitem__
        )
        consensus_rows.append(
            (tuple((a + b) / 2 for a, b in zip(kalshi, polymarket)), label)
        )
        kalshi_overlap_rows.append((kalshi, label))
        polymarket_overlap_rows.append((polymarket, label))
        model_overlap_rows.append((_probs(source["model"][key]), label))
    divergences.sort()

    def percentile(q: float) -> float:
        position = (len(divergences) - 1) * q
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return divergences[lower]
        weight = position - lower
        return divergences[lower] * (1 - weight) + divergences[upper] * weight

    return {
        "generated_from": str(DEFAULT_INPUT.relative_to(ROOT)),
        "input_sha256": input_sha256,
        "study": "2026 World Cup pre-kickoff 1X2 venue calibration",
        "venues": venues,
        "cross_venue": {
            "n_matches": len(overlap),
            "median_max_outcome_divergence": percentile(0.5),
            "p90_max_outcome_divergence": percentile(0.9),
            "max_outcome_divergence": max(divergences),
            "diverging_at_least_3c": sum(value >= 0.03 for value in divergences),
            "favorite_disagreements": favorite_disagreements,
            "log_loss": {
                "kalshi": _metrics(kalshi_overlap_rows)["log_loss"],
                "polymarket": _metrics(polymarket_overlap_rows)["log_loss"],
                "consensus": _metrics(consensus_rows)["log_loss"],
                "model": _metrics(model_overlap_rows)["log_loss"],
            },
        },
        "method": {
            "bootstrap": {
                "unit": "match",
                "seed": BOOTSTRAP_SEED,
                "samples": BOOTSTRAP_SAMPLES,
                "note": "Recomputed interval; historical published CI is retained separately because its original seed was not recorded.",
            },
            "population": "All 104 WC26 matches; venue rows require all three 1X2 outcomes.",
            "grading": "Regulation-time home/draw/away result.",
            "devigging": "Proportional normalization to sum each three-outcome vector to one.",
            "snapshots": "Last reconstructed pre-kickoff observation; not simultaneous across venues.",
            "limitations": [
                "Historical prices were reconstructed post-hoc at different fidelities.",
                "The audit measures pre-kickoff 1X2 only, not in-play or derived markets.",
                "The original CI seed was not recorded; its published intervals are frozen evidence values.",
                "Consensus is evaluated as robustness context, not claimed as an accuracy improvement.",
            ],
        },
    }


def generate(input_path: Path, output_path: Path) -> dict[str, Any]:
    raw = input_path.read_bytes()
    source = json.loads(raw)
    audit = build_audit(source, input_sha256=hashlib.sha256(raw).hexdigest())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.input, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
