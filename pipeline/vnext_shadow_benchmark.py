"""Read-only benchmark for one exact vNext shadow tag against its champion.

The adapter deliberately works from the append-only ``Prediction`` ledger
instead of ``PredictionResult``: that result table has only one shadow slot per
match and cannot safely represent multiple independently versioned challengers.
Each challenger is paired to the exact earlier champion payload named by its
validated receipt.  The function performs no writes.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Hashable, Sequence
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import Match, Prediction
from ml.models.poisson import goal_markets
from ml.evaluation.paired_challenger import (
    PromotionPolicy,
    benchmark_paired_challenger,
    promotion_gate,
)
from pipeline.vnext_shadow import (
    champion_row_fingerprint,
    extract_vnext_receipt,
    validate_vnext_receipt,
)

_KNOCKOUT_STAGES = {"r32", "r16", "qf", "sf", "third_place", "final"}


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        # SQLite drops timezone information. Repository timestamps are UTC, so
        # interpreting its naive round-trip as UTC is deterministic.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _latest_before(
    rows: Iterable[Prediction], kickoff: datetime
) -> Prediction | None:
    eligible = [
        row
        for row in rows
        if row.created_at is not None
        and _utc(row.created_at, "prediction.created_at") < kickoff
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (_utc(row.created_at, "prediction.created_at"), row.id),
    )


def _ledger_position(row: Prediction) -> tuple[datetime, int]:
    if row.created_at is None:
        raise ValueError("prediction.created_at is required")
    return _utc(row.created_at, "prediction.created_at"), row.id


def _linked_pair_before(
    challenger_rows: Iterable[Prediction],
    champion_rows: Iterable[Prediction],
    *,
    kickoff: datetime,
    champion_version: str,
    challenger_tag: str,
) -> tuple[Prediction | None, Prediction | None, dict[str, object] | None, int]:
    """Return the latest receipt-valid challenger and its content-linked parent."""
    candidates = sorted(
        (
            row
            for row in challenger_rows
            if row.created_at is not None
            and _utc(row.created_at, "prediction.created_at") < kickoff
        ),
        key=_ledger_position,
        reverse=True,
    )
    parents = [
        row
        for row in champion_rows
        if row.created_at is not None
        and _utc(row.created_at, "prediction.created_at") < kickoff
    ]
    invalid = 0
    for challenger in candidates:
        try:
            receipt = extract_vnext_receipt(challenger.reasons)
            if receipt is None:
                raise ValueError("missing vNext receipt")
            receipt = validate_vnext_receipt(
                receipt,
                challenger_tag=challenger_tag,
                champion_model_version=champion_version,
                kickoff_utc=kickoff,
            )
            expected_fingerprint = receipt["champion_payload_sha256"]
            challenger_position = _ledger_position(challenger)
            matching = [
                row
                for row in parents
                if _ledger_position(row) <= challenger_position
                and champion_row_fingerprint(row) == expected_fingerprint
            ]
            if not matching:
                raise ValueError("receipt has no matching champion parent")
            parent = max(matching, key=_ledger_position)
            receipt = validate_vnext_receipt(
                receipt,
                challenger_tag=challenger_tag,
                champion_model_version=champion_version,
                kickoff_utc=kickoff,
                champion_payload_sha256=champion_row_fingerprint(parent),
                champion_created_at=parent.created_at,
                challenger_created_at=challenger.created_at,
            )
            return parent, challenger, receipt, invalid
        except (TypeError, ValueError):
            invalid += 1
    return None, None, None, invalid


def _probabilities(row: Prediction) -> tuple[float, float, float]:
    return row.prob_home_win, row.prob_draw, row.prob_away_win


def _regulation_score(match: Match) -> tuple[int, int] | None:
    if match.score_home_90 is not None and match.score_away_90 is not None:
        return match.score_home_90, match.score_away_90
    else:
        if (match.stage or "").lower() in _KNOCKOUT_STAGES:
            # A knockout final score may include extra time.  Without the 90'
            # snapshot we cannot honestly label the prematch W/D/L forecast.
            return None
        home, away = match.score_home, match.score_away
    if home is None or away is None:
        raise ValueError("finished benchmark match has no usable score")
    return home, away


def _regulation_label(score: tuple[int, int]) -> str:
    home, away = score
    if home > away:
        return "H"
    return "A" if home < away else "D"


def _champion_over_2_5(row: Prediction) -> float | None:
    markets = goal_markets(row.lambda_home, row.lambda_away, row.rho)
    if markets is None:
        return None
    return float(markets["total"]["over_2_5"])


def _binary_metrics(probabilities: Sequence[float], labels: Sequence[int]) -> dict:
    losses: list[float] = []
    briers: list[float] = []
    correct: list[float] = []
    for probability, label in zip(probabilities, labels):
        probability = float(probability)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError("binary probabilities must be finite and within [0, 1]")
        clipped = max(1e-15, min(1.0 - 1e-15, probability))
        losses.append(
            -(label * math.log(clipped) + (1 - label) * math.log(1.0 - clipped))
        )
        briers.append((probability - label) ** 2)
        correct.append(float((probability >= 0.5) == bool(label)))
    return {
        "log_loss": sum(losses) / len(losses),
        "brier": sum(briers) / len(briers),
        "accuracy": sum(correct) / len(correct),
        "_losses": losses,
        "_briers": briers,
        "_correct": correct,
    }


def _cluster_mean_ci(
    values: Sequence[float],
    clusters: Sequence[Hashable],
    *,
    n_bootstrap: int,
    seed: int,
) -> tuple[float, float]:
    if n_bootstrap < 100:
        raise ValueError("n_bootstrap must be at least 100")
    grouped: dict[Hashable, list[float]] = defaultdict(list)
    for cluster, value in zip(clusters, values):
        grouped[cluster].append(value)
    keys = list(grouped)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(n_bootstrap):
        drawn: list[float] = []
        for _ in keys:
            drawn.extend(grouped[keys[rng.randrange(len(keys))]])
        samples.append(sum(drawn) / len(drawn))
    samples.sort()
    return (
        samples[int(0.025 * len(samples))],
        samples[min(len(samples) - 1, int(0.975 * len(samples)))],
    )


def _binary_benchmark(
    champion: Sequence[float],
    challenger: Sequence[float],
    labels: Sequence[int],
    clusters: Sequence[Hashable],
    *,
    n_bootstrap: int,
    seed: int,
) -> dict:
    champion_metrics = _binary_metrics(champion, labels)
    challenger_metrics = _binary_metrics(challenger, labels)
    deltas = {
        "log_loss": [
            new - old
            for old, new in zip(
                champion_metrics.pop("_losses"),
                challenger_metrics.pop("_losses"),
            )
        ],
        "brier": [
            new - old
            for old, new in zip(
                champion_metrics.pop("_briers"),
                challenger_metrics.pop("_briers"),
            )
        ],
        "accuracy": [
            new - old
            for old, new in zip(
                champion_metrics.pop("_correct"),
                challenger_metrics.pop("_correct"),
            )
        ],
    }
    summary: dict[str, object] = {}
    for offset, (name, values) in enumerate(deltas.items()):
        summary[name] = sum(values) / len(values)
        summary[f"{name}_ci95"] = _cluster_mean_ci(
            values,
            clusters,
            n_bootstrap=n_bootstrap,
            seed=seed + offset,
        )
    low, high = summary["log_loss_ci95"]
    verdict = "no_credible_difference"
    if high < 0.0:
        verdict = "challenger_beats_champion"
    elif low > 0.0:
        verdict = "champion_beats_challenger"
    return {
        "market": "over_under_2_5",
        "n_matches": len(labels),
        "n_clusters": len(set(clusters)),
        "champion": champion_metrics,
        "challenger": challenger_metrics,
        "delta": summary,
        "verdict": verdict,
    }


def benchmark_stored_vnext_shadow(
    db: Session,
    *,
    champion_version: str,
    challenger_tag: str,
    tournament_id: int | None = None,
    policy: PromotionPolicy = PromotionPolicy(),
    n_bootstrap: int = 5_000,
    seed: int = 2026,
) -> dict:
    """Compare exact champion/challenger tags on identical pre-kickoff rows.

    ``eligible_matches`` means finished matches with an exact-version champion
    forecast before kickoff. Challenger coverage is measured against that set.
    Tournament IDs are the resampling clusters, preventing matches from one
    competition from being treated as independent seasons/tournaments.
    """
    for value, name in (
        (champion_version, "champion_version"),
        (challenger_tag, "challenger_tag"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if champion_version == challenger_tag:
        raise ValueError("champion and challenger versions must differ")

    # A diagnostic read must not autoflush unrelated pending caller state.
    with db.no_autoflush:
        query = (
            db.query(Match)
            .filter(Match.status == "finished")
            .filter(Match.kickoff_utc.isnot(None))
            .filter(Match.score_home.isnot(None), Match.score_away.isnot(None))
        )
        if tournament_id is not None:
            query = query.filter(Match.tournament_id == tournament_id)
        matches = query.order_by(Match.kickoff_utc, Match.id).all()
        match_ids = [match.id for match in matches]

        predictions: list[Prediction] = []
        if match_ids:
            predictions = (
                db.query(Prediction)
                .filter(Prediction.match_id.in_(match_ids))
                .filter(
                    or_(
                        and_(
                            Prediction.model_version == champion_version,
                            Prediction.is_shadow.is_(False),
                        ),
                        and_(
                            Prediction.model_version == challenger_tag,
                            Prediction.is_shadow.is_(True),
                        ),
                    )
                )
                .all()
            )
    champion_rows: dict[int, list[Prediction]] = defaultdict(list)
    challenger_rows: dict[int, list[Prediction]] = defaultdict(list)
    for row in predictions:
        if row.model_version == champion_version and not row.is_shadow:
            champion_rows[row.match_id].append(row)
        elif row.model_version == challenger_tag and row.is_shadow:
            challenger_rows[row.match_id].append(row)

    champions: list[tuple[float, float, float]] = []
    challengers: list[tuple[float, float, float]] = []
    labels: list[str] = []
    clusters: list[str] = []
    champion_over_2_5: list[float] = []
    challenger_over_2_5: list[float] = []
    over_2_5_labels: list[int] = []
    goal_market_clusters: list[str] = []
    goal_market_match_ids: list[int] = []
    paired_match_ids: list[int] = []
    paired_prediction_ids: list[dict[str, int]] = []
    eligible_matches = 0
    excluded_missing_regulation_score = 0
    invalid_or_unlinked_challenger_rows = 0
    for match in matches:
        regulation_score = _regulation_score(match)
        if regulation_score is None:
            excluded_missing_regulation_score += 1
            continue
        label = _regulation_label(regulation_score)
        kickoff = _utc(match.kickoff_utc, "match.kickoff_utc")
        latest_champion = _latest_before(champion_rows[match.id], kickoff)
        if latest_champion is None:
            continue
        eligible_matches += 1
        champion, challenger, receipt, invalid = _linked_pair_before(
            challenger_rows[match.id],
            champion_rows[match.id],
            kickoff=kickoff,
            champion_version=champion_version,
            challenger_tag=challenger_tag,
        )
        invalid_or_unlinked_challenger_rows += invalid
        if champion is None or challenger is None or receipt is None:
            continue
        cluster = f"tournament:{match.tournament_id}"
        champions.append(_probabilities(champion))
        challengers.append(_probabilities(challenger))
        labels.append(label)
        clusters.append(cluster)
        paired_match_ids.append(match.id)
        paired_prediction_ids.append(
            {
                "match_id": match.id,
                "champion_prediction_id": champion.id,
                "challenger_prediction_id": challenger.id,
            }
        )
        champion_over = _champion_over_2_5(champion)
        if champion_over is not None:
            champion_over_2_5.append(champion_over)
            challenger_over_2_5.append(float(receipt["candidate_over_2_5"]))
            over_2_5_labels.append(int(sum(regulation_score) >= 3))
            goal_market_clusters.append(cluster)
            goal_market_match_ids.append(match.id)

    base = {
        "champion_version": champion_version,
        "challenger_tag": challenger_tag,
        "scope": {"tournament_id": tournament_id},
        "total_finished_matches": len(matches),
        "eligible_matches": eligible_matches,
        "paired_matches": len(paired_match_ids),
        "paired_match_ids": paired_match_ids,
        "paired_prediction_ids": paired_prediction_ids,
        "goal_market_paired_matches": len(goal_market_match_ids),
        "goal_market_paired_match_ids": goal_market_match_ids,
        "excluded_missing_regulation_score": excluded_missing_regulation_score,
        "invalid_or_unlinked_challenger_rows": invalid_or_unlinked_challenger_rows,
        "coverage": (
            len(paired_match_ids) / eligible_matches if eligible_matches else 0.0
        ),
    }
    if not paired_match_ids:
        return {
            **base,
            "benchmark": None,
            "goal_market_benchmark": None,
            "wdl_guardrail": None,
            "promotion": {
                "promote": False,
                "coverage": base["coverage"],
                "reasons": [
                    "no paired pre-kickoff predictions",
                    "no candidate goal-total evidence is available",
                ],
            },
        }

    benchmark = benchmark_paired_challenger(
        champions,
        challengers,
        labels,
        clusters=clusters,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    raw_wdl_gate = promotion_gate(
        benchmark,
        eligible_matches=eligible_matches,
        policy=policy,
    )
    wdl_guardrail = {
        "passes_superiority_gate": raw_wdl_gate["promote"],
        **{key: value for key, value in raw_wdl_gate.items() if key != "promote"},
    }
    goal_market_benchmark = None
    if goal_market_match_ids:
        goal_market_benchmark = _binary_benchmark(
            champion_over_2_5,
            challenger_over_2_5,
            over_2_5_labels,
            goal_market_clusters,
            n_bootstrap=n_bootstrap,
            seed=seed + 10,
        )
    promotion_reasons = [
        "automatic promotion is disabled; this command is evidence-only"
    ]
    if goal_market_benchmark is None:
        promotion_reasons.append("candidate goal-total metric is unavailable")
    return {
        **base,
        "benchmark": benchmark,
        "goal_market_benchmark": goal_market_benchmark,
        "wdl_guardrail": wdl_guardrail,
        "promotion": {
            "promote": False,
            "coverage": base["coverage"],
            "reasons": promotion_reasons,
        },
    }
