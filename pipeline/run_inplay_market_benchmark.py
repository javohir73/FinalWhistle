"""Run the precommitted P3 benchmark from a frozen JSON observation ledger."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from sqlalchemy.orm import Session

from app.models import Match, VenueMarket, VenuePriceTick
from ml.evaluation.market_benchmark import InPlayObservation, benchmark_inplay


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def load_observations(path: Path) -> list[InPlayObservation]:
    source = json.loads(path.read_text())
    rows = []
    for index, row in enumerate(source):
        try:
            rows.append(InPlayObservation(
                match_id=int(row["match_id"]), venue=str(row["venue"]), market_type=str(row["market_type"]),
                minute=float(row["minute"]) if row.get("minute") is not None else None,
                period=str(row["period"]), model_probs=tuple(map(float, row["model_probs"])),
                venue_probs=tuple(map(float, row["venue_probs"])), label=int(row["label"]),
                tick_ts=_dt(row["tick_ts"]), model_state_ts=_dt(row["model_state_ts"]),
                quote_source_ts=_dt(row.get("quote_source_ts")), model_score=tuple(map(int, row["model_score"])),
                venue_score=tuple(map(int, row["venue_score"])), mapping_status=str(row.get("mapping_status", "mapped")),
                supported=bool(row.get("supported", True)), settled_at=_dt(row.get("settled_at")),
                competition=str(row.get("competition", "unknown")),
                model_cards=tuple(map(int, row["model_cards"])),
                venue_cards=tuple(map(int, row["venue_cards"])),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid observation row {index + 1}: {exc}") from exc
    return rows


@dataclass(frozen=True)
class PureModelLedgerPoint:
    """Frozen pure-model state supplied by the in-play model ledger."""

    event_id: int
    observed_at: datetime
    minute: float | None
    period: str
    score: tuple[int, int]
    outcome_probs: dict[str, float]
    competition: str
    cards: tuple[int, int] = (0, 0)


_SCORE_STATE = re.compile(r"(?:^|;)score:(\d+)-(\d+)(?:;|$)")
_CARD_STATE = re.compile(r"(?:^|;)cards:(\d+)-(\d+)(?:;|$)")


def _distance_seconds(left: datetime, right: datetime) -> float:
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return abs((left.astimezone(timezone.utc) - right.astimezone(timezone.utc)).total_seconds())


def _venue_score(clock_state: str | None) -> tuple[int, int]:
    if not clock_state:
        return (-1, -1)
    match = _SCORE_STATE.search(clock_state)
    return (int(match.group(1)), int(match.group(2))) if match else (-1, -1)


def _venue_cards(clock_state: str | None) -> tuple[int, int]:
    if not clock_state:
        return (-1, -1)
    match = _CARD_STATE.search(clock_state)
    return (int(match.group(1)), int(match.group(2))) if match else (-1, -1)


def load_observations_from_db(
    db: Session,
    model_ledger: list[PureModelLedgerPoint],
    *,
    max_alignment_seconds: float = 10,
) -> tuple[list[InPlayObservation], dict[str, int]]:
    """Join settled mapped ticks to a separately frozen pure-model ledger.

    Binary venue contracts are represented as `(P(outcome), 1-P(outcome))`.
    Missing state, midpoint, settlement direction, or pure-model values are
    reported and never guessed. The benchmark later rejects sentinel score
    state as mismatched.
    """
    by_event: dict[int, list[PureModelLedgerPoint]] = {}
    for point in model_ledger:
        by_event.setdefault(point.event_id, []).append(point)
    rows = (
        db.query(VenuePriceTick, VenueMarket, Match)
        .join(VenueMarket, VenueMarket.id == VenuePriceTick.venue_market_id)
        .join(Match, Match.id == VenueMarket.canonical_event_id)
        .filter(
            VenueMarket.mapping_status == "mapped",
            VenueMarket.canonical_outcome.isnot(None),
            VenueMarket.settled_at.isnot(None),
            Match.status == "finished",
        )
        .all()
    )
    observations = []
    excluded = Counter()
    for tick, market, _match in rows:
        probability = tick.mid
        if probability is None:
            excluded["missing_two_sided_midpoint"] += 1
            continue
        outcome = market.canonical_outcome
        candidates = [
            point for point in by_event.get(market.canonical_event_id, [])
            if outcome in point.outcome_probs
            and _distance_seconds(tick.ts, point.observed_at) <= max_alignment_seconds
        ]
        if not candidates:
            excluded["missing_aligned_pure_model_state"] += 1
            continue
        point = min(candidates, key=lambda item: (_distance_seconds(tick.ts, item.observed_at), item.observed_at))
        model_probability = point.outcome_probs[outcome]
        if not 0 <= model_probability <= 1:
            excluded["invalid_pure_model_probability"] += 1
            continue
        settled = (market.settled_outcome or "").casefold()
        if settled in {"yes", outcome.casefold()}:
            label = 0
        elif settled == "no":
            label = 1
        else:
            excluded["unsupported_settlement_direction"] += 1
            continue
        observations.append(InPlayObservation(
            match_id=market.canonical_event_id,
            venue=market.venue,
            market_type=f"{market.market_type}:{outcome}",
            minute=point.minute,
            period=point.period,
            model_probs=(model_probability, 1 - model_probability),
            venue_probs=(probability, 1 - probability),
            label=label,
            tick_ts=tick.ts,
            model_state_ts=point.observed_at,
            quote_source_ts=tick.source_ts,
            model_score=point.score,
            venue_score=_venue_score(tick.clock_state),
            mapping_status=market.mapping_status,
            supported=True,
            settled_at=market.settled_at,
            competition=point.competition,
            model_cards=point.cards,
            venue_cards=_venue_cards(tick.clock_state),
        ))
    return observations, dict(sorted(excluded.items()))


def run(input_path: Path, precommit_path: Path, output_dir: Path) -> dict:
    config = json.loads(precommit_path.read_text())
    observations = load_observations(input_path)
    result = benchmark_inplay(
        observations,
        held_out_cutoff=datetime.fromisoformat(config["held_out_cutoff"]),
        max_alignment_seconds=float(config["max_alignment_seconds"]),
        max_quote_age_seconds=float(config["max_quote_age_seconds"]),
        minimum_matches=int(config["minimum_matches"]),
        n_bootstrap=int(config["bootstrap_samples"]),
        seed=int(config["bootstrap_seed"]),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = ["P3 in-play market benchmark", "", f"Input observations: {result['population']['input_observations']}", f"Included: {result['population']['included_observations']}", f"Exclusions: {json.dumps(result['population']['exclusions'], sort_keys=True)}", ""]
    for group in result["groups"]:
        lines.append(f"{group['venue']} / {group['market_type']} / {group['horizon']}: {group['status']} ({group['sample_matches']} matches, {group['paired_ticks']} ticks), verdict={group['verdict']}")
    (output_dir / "report.txt").write_text("\n".join(lines) + "\n")
    evidence = [
        "# In-play market benchmark evidence card", "",
        f"- Frozen input: `{input_path}`", f"- Precommit: `{precommit_path}`",
        "- Command: `PYTHONPATH=backend:. python -m pipeline.run_inplay_market_benchmark --input <ledger.json> --precommit <precommit.json> --output-dir <dir>`",
        f"- Bootstrap: match-clustered, seed {config['bootstrap_seed']}, {config['bootstrap_samples']} samples",
        "- Result: see `results.json`; insufficient groups remain insufficient and are not pooled.",
        "- Scope: pure-model ledger only; venue and market types are separated.",
    ]
    (output_dir / "EVIDENCE-CARD.md").write_text("\n".join(evidence) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--precommit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.precommit, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
