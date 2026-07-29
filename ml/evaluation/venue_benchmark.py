"""Shadow benchmark: model vs venue-implied 1X2 vs a fit-free baseline.

Pure evaluation -- no I/O, no DB, nothing fitted, nothing served. This module
answers exactly one research question: on finished, verified-mapped fixtures
with a pre-kickoff venue quote, how do the production model's 1X2
probabilities compare to the venue's vig-normalized ones? It is NOT the
pre-registered API-Football closing-line gate (`ml/evaluation/
market_benchmark.py` + `pipeline/run_calibrator_benchmark.py`), which stays
frozen and untouched.

Design rules, each with an adversarial test:

* **The unit is the canonical match, never a tick or market row.** One
  observation per (venue, match); splits move whole matches, so every
  observation for a match lands on the same side and holdout matches are
  chronologically after every train match.
* **Fail closed.** A non-finite probability, an out-of-domain price, a naive
  timestamp, a post-kickoff quote, an unknown outcome or an impossible book
  sum is a constructor error -- not a row that quietly skews a mean.
* **NOT READY never ranks.** Below the minimum match count the result is a
  sample-size statement with no verdict and no ordering. Uncertainty is a
  match-clustered bootstrap on per-match log-loss differences, reported only
  when it is computable.
* **Nothing is trained here.** The baseline is uniform (1/3, 1/3, 1/3)
  precisely because it needs no fitting and can leak nothing. The
  chronological split exists so any FUTURE calibration fit has a train side
  to live on; today nothing reads the train side but the diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Mapping, Sequence

BENCHMARK_VERSION = "venue-benchmark-v1"

OUTCOMES = ("home", "draw", "away")
_OUTCOME_INDEX = {name: index for index, name in enumerate(OUTCOMES)}

#: Below this many holdout matches a group is NOT READY: no verdict, no
#: ranking, no deltas presented as findings. Research floor, not a strength
#: claim -- the pre-registered odds gate keeps its own far larger minimum.
DEFAULT_MIN_MATCHES = 50

#: A 1X2 book whose raw implied sum falls outside this band is not a
#: plausible three-way market snapshot; it is excluded and counted, never
#: normalized into respectability.
BOOK_SUM_RANGE = (0.85, 1.30)

DEFAULT_HOLDOUT_FRACTION = 0.3
_EPS = 1e-12

NOT_READY = "NOT_READY"
READY = "READY"


class BenchmarkInputError(ValueError):
    """An observation that must not enter the benchmark."""


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise BenchmarkInputError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise BenchmarkInputError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _probs(values, name: str) -> tuple[float, float, float]:
    try:
        triple = tuple(float(v) for v in values)
    except (TypeError, ValueError):
        raise BenchmarkInputError(f"{name} must be three numbers") from None
    if len(triple) != 3:
        raise BenchmarkInputError(f"{name} must have exactly three entries")
    for v in triple:
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise BenchmarkInputError(f"{name} contains an out-of-domain value: {v!r}")
    return triple  # type: ignore[return-value]


@dataclass(frozen=True)
class MatchObservation:
    """One (venue, match) pair, fully validated at construction.

    ``venue_probs_raw`` are the venue's own mid prices, retained untouched;
    ``venue_probs`` is their explicit vig-normalization. Both live on the
    observation so a report can always show what the venue actually said next
    to what was scored.
    """

    match_id: int
    venue: str
    competition: str
    kickoff_utc: datetime
    captured_at: datetime
    outcome: str
    model_probs: tuple[float, float, float]
    venue_probs_raw: tuple[float, float, float]
    venue_probs: tuple[float, float, float] = field(init=False)
    book_sum: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kickoff_utc", _aware(self.kickoff_utc, "kickoff_utc"))
        object.__setattr__(self, "captured_at", _aware(self.captured_at, "captured_at"))
        if self.captured_at > self.kickoff_utc:
            raise BenchmarkInputError(
                "captured_at is after kickoff: a post-kickoff quote is not a "
                "pre-match snapshot"
            )
        if self.outcome not in _OUTCOME_INDEX:
            raise BenchmarkInputError(f"unknown outcome {self.outcome!r}")
        if not str(self.venue).strip() or not str(self.competition).strip():
            raise BenchmarkInputError("venue and competition must be non-empty")
        model = _probs(self.model_probs, "model_probs")
        model_sum = sum(model)
        if not 0.99 <= model_sum <= 1.01:
            raise BenchmarkInputError(
                f"model_probs sum to {model_sum:.4f}, not a probability vector"
            )
        object.__setattr__(
            self, "model_probs", tuple(v / model_sum for v in model))
        raw = _probs(self.venue_probs_raw, "venue_probs_raw")
        book_sum = sum(raw)
        if not BOOK_SUM_RANGE[0] <= book_sum <= BOOK_SUM_RANGE[1]:
            raise BenchmarkInputError(
                f"book sum {book_sum:.4f} outside plausible range "
                f"{BOOK_SUM_RANGE}; refusing to normalize an implausible book"
            )
        object.__setattr__(self, "venue_probs_raw", raw)
        object.__setattr__(self, "book_sum", book_sum)
        object.__setattr__(
            self, "venue_probs", tuple(v / book_sum for v in raw))

    @property
    def outcome_index(self) -> int:
        return _OUTCOME_INDEX[self.outcome]


UNIFORM = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)


def chronological_split(
    observations: Sequence[MatchObservation],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> tuple[list[MatchObservation], list[MatchObservation], dict]:
    """Split BY CANONICAL MATCH, chronologically. Whole matches move together.

    Splitting rows would let one match's kalshi observation train what its
    polymarket observation is judged on. The boundary is a match kickoff:
    every holdout match kicks off at or after the boundary, every train match
    before it. Diagnostics report per-competition membership so a competition
    that exists only in holdout is visible, not a surprise.
    """
    if not 0.0 < holdout_fraction < 1.0:
        raise BenchmarkInputError("holdout_fraction must be inside (0, 1)")
    matches: dict[int, datetime] = {}
    for observation in observations:
        kickoff = matches.get(observation.match_id)
        if kickoff is not None and kickoff != observation.kickoff_utc:
            raise BenchmarkInputError(
                f"match {observation.match_id} appears with two different "
                "kickoffs; conflicting fixture data must be resolved upstream"
            )
        matches[observation.match_id] = observation.kickoff_utc
    ordered = sorted(matches.items(), key=lambda item: (item[1], item[0]))
    holdout_count = math.ceil(len(ordered) * holdout_fraction) if ordered else 0
    holdout_ids = {match_id for match_id, _ in ordered[len(ordered) - holdout_count:]}
    train = [o for o in observations if o.match_id not in holdout_ids]
    holdout = [o for o in observations if o.match_id in holdout_ids]

    competitions: dict[str, dict[str, set]] = defaultdict(
        lambda: {"train": set(), "holdout": set()})
    for observation in observations:
        side = "holdout" if observation.match_id in holdout_ids else "train"
        competitions[observation.competition][side].add(observation.match_id)
    diagnostics = {
        "split_by": "canonical match, chronological on kickoff",
        "train_matches": len(ordered) - holdout_count,
        "holdout_matches": holdout_count,
        "holdout_fraction": holdout_fraction,
        "boundary_kickoff": (
            ordered[len(ordered) - holdout_count][1].isoformat()
            if holdout_count else None),
        "competitions": {
            name: {
                "train_matches": len(sides["train"]),
                "holdout_matches": len(sides["holdout"]),
                "holdout_only": not sides["train"] and bool(sides["holdout"]),
            }
            for name, sides in sorted(competitions.items())
        },
    }
    return train, holdout, diagnostics


def _log_loss(probs: Sequence[float], outcome_index: int) -> float:
    return -math.log(max(probs[outcome_index], _EPS))


def _brier(probs: Sequence[float], outcome_index: int) -> float:
    return sum(
        (p - (1.0 if i == outcome_index else 0.0)) ** 2
        for i, p in enumerate(probs)
    )


def _reliability(rows: list[tuple[tuple[float, float, float], int]]) -> dict:
    """Ten-bin reliability over every (outcome-slot, probability) pair."""
    bins: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for probs, outcome_index in rows:
        for slot, p in enumerate(probs):
            bins[min(9, int(p * 10))].append((p, slot == outcome_index))
    total = sum(len(v) for v in bins.values())
    table = []
    ece = 0.0
    for bin_index in sorted(bins):
        values = bins[bin_index]
        confidence = sum(p for p, _ in values) / len(values)
        frequency = sum(hit for _, hit in values) / len(values)
        ece += len(values) / total * abs(confidence - frequency)
        table.append({
            "bin": f"{bin_index / 10:.1f}-{(bin_index + 1) / 10:.1f}",
            "n": len(values),
            "mean_predicted": round(confidence, 4),
            "observed_frequency": round(frequency, 4),
        })
    return {"ece": round(ece, 4), "bins": table}


def _metrics(rows: list[tuple[tuple[float, float, float], int]]) -> dict:
    n = len(rows)
    return {
        "log_loss": round(sum(_log_loss(p, y) for p, y in rows) / n, 6),
        "brier": round(sum(_brier(p, y) for p, y in rows) / n, 6),
        "n": n,
        "reliability": _reliability(rows),
    }


def _clustered_delta_ci(
    deltas_by_match: Mapping[int, float], *, n_bootstrap: int, seed: int
) -> tuple[float, float] | None:
    """Match-clustered bootstrap CI on the mean per-match delta."""
    match_ids = sorted(deltas_by_match)
    if len(match_ids) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_bootstrap):
        sample = [deltas_by_match[match_ids[rng.randrange(len(match_ids))]]
                  for _ in match_ids]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int(0.025 * n_bootstrap)]
    high = means[min(n_bootstrap - 1, int(0.975 * n_bootstrap))]
    return (round(low, 6), round(high, 6))


def evaluate_holdout(
    holdout: Sequence[MatchObservation],
    *,
    min_matches: int = DEFAULT_MIN_MATCHES,
    n_bootstrap: int = 2000,
    seed: int = 20260729,
) -> dict:
    """Per-venue comparison on identical eligible matches. Deterministic.

    Every venue group scores model, normalized venue and the uniform baseline
    on exactly the same matches. A group below ``min_matches`` is NOT_READY:
    counts only, no verdict, no ranking, no deltas -- a tiny sample ranked is
    a lie with error bars.
    """
    groups: dict[str, list[MatchObservation]] = defaultdict(list)
    for observation in holdout:
        groups[observation.venue].append(observation)

    results = []
    for venue in sorted(groups):
        rows = sorted(groups[venue], key=lambda o: (o.kickoff_utc, o.match_id))
        n_matches = len({o.match_id for o in rows})
        if len(rows) != n_matches:
            raise BenchmarkInputError(
                f"venue {venue!r} has more observations than matches; the "
                "unit of comparison is the match"
            )
        entry: dict = {
            "venue": venue,
            "n_matches": n_matches,
            "capture_window": {
                "first_kickoff": rows[0].kickoff_utc.isoformat(),
                "last_kickoff": rows[-1].kickoff_utc.isoformat(),
            },
            "outcome_counts": dict(sorted(Counter(o.outcome for o in rows).items())),
            "mean_book_sum": round(
                sum(o.book_sum for o in rows) / len(rows), 4),
            "min_matches": min_matches,
        }
        if n_matches < min_matches:
            entry["status"] = NOT_READY
            entry["reason"] = (
                f"{n_matches} matches < minimum {min_matches}; no verdict and "
                "no ranking on a sample this small"
            )
            results.append(entry)
            continue

        model_rows = [(o.model_probs, o.outcome_index) for o in rows]
        venue_rows = [(o.venue_probs, o.outcome_index) for o in rows]
        baseline_rows = [(UNIFORM, o.outcome_index) for o in rows]
        deltas = {
            o.match_id: _log_loss(o.model_probs, o.outcome_index)
            - _log_loss(o.venue_probs, o.outcome_index)
            for o in rows
        }
        ci = _clustered_delta_ci(deltas, n_bootstrap=n_bootstrap, seed=seed)
        verdict = "inconclusive"
        if ci is not None:
            if ci[1] < 0:
                verdict = "model_beats_venue"
            elif ci[0] > 0:
                verdict = "venue_beats_model"
        entry.update({
            "status": READY,
            "model": _metrics(model_rows),
            "venue_normalized": _metrics(venue_rows),
            "baseline_uniform": _metrics(baseline_rows),
            "delta_log_loss_model_minus_venue": round(
                sum(deltas.values()) / len(deltas), 6),
            "delta_ci95_match_clustered": list(ci) if ci else None,
            "bootstrap": {"unit": "match", "samples": n_bootstrap, "seed": seed},
            "verdict": verdict,
        })
        results.append(entry)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "outcome_order": list(OUTCOMES),
        "baseline": "uniform (1/3, 1/3, 1/3) — fit-free by construction",
        "groups": results,
    }


def run_benchmark(
    observations: Sequence[MatchObservation],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_matches: int = DEFAULT_MIN_MATCHES,
    n_bootstrap: int = 2000,
    seed: int = 20260729,
) -> dict:
    """Split chronologically, evaluate the holdout, report the lineage."""
    train, holdout, split = chronological_split(
        observations, holdout_fraction=holdout_fraction)
    evaluation = evaluate_holdout(
        holdout, min_matches=min_matches, n_bootstrap=n_bootstrap, seed=seed)
    return {
        **evaluation,
        "split": split,
        "note": (
            "holdout-only evaluation; the train side exists for future "
            "calibration fitting and is not read by any metric here"
        ),
    }
