# ml/models/availability.py
"""Player-availability adjustment for the match forecast (announced-XI only, v1).

Turns "who is actually in the announced XI" into a bounded, explainable offset to
a team's expected goals, reusing the goalscorers attacking weights. Pure functions
— no I/O, no DB. Shadow-first: the caller logs the adjusted forecast as a twin and
surfaces the explanation as context; it does not move the published number.
See docs/superpowers/specs/2026-07-03-availability-signal-design.md.
"""
from __future__ import annotations

import math

from ml.models.goalscorers import player_rate

# Attack offset clamp (log-lambda units). Deliberately asymmetric and tight: a
# missing player almost always subtracts, and the clamp guarantees a garbled or
# empty XI can never wreck a forecast. -0.25 ~= -22% attack, +0.10 ~= +10%.
ATTACK_OFFSET_LO = -0.25
ATTACK_OFFSET_HI = 0.10
REFERENCE_XI_SIZE = 11

DOUBTFUL_WEIGHT = 0.5


def _rate(p: dict) -> float:
    """A player's shrunk goals-per-90 (attacking weight) via goalscorers.player_rate."""
    return player_rate(
        p.get("club_goals"), p.get("club_minutes"),
        p.get("wc_goals"), p.get("wc_minutes"), p.get("position"),
    )


def attack_capacity(players: list[dict]) -> float:
    """Sum of shrunk goals-per-90 over the given players — a rough 'how much
    scoring these individuals bring'. Reuses goalscorers.player_rate."""
    return sum(_rate(p) for p in players)


def reference_eleven(squad: list[dict]) -> list[dict]:
    """The squad's top eleven by total (club+WC) minutes — the usual starters."""
    return sorted(
        squad,
        key=lambda p: (p.get("club_minutes") or 0) + (p.get("wc_minutes") or 0),
        reverse=True,
    )[:REFERENCE_XI_SIZE]


def _clamped_offset(effective: float, reference: float) -> tuple[float, float] | None:
    """(offset, attack_delta_pct) from an effective/reference capacity ratio, or
    None when the reference capacity is ~0. Shared by the XI and injury paths so
    the clamp lives in exactly one place. attack_delta_pct = exp(offset) - 1."""
    if reference <= 0.0:
        return None
    ratio = effective / reference
    if ratio <= 0.0:
        offset = ATTACK_OFFSET_LO
    else:
        offset = max(ATTACK_OFFSET_LO, min(ATTACK_OFFSET_HI, math.log(ratio)))
    return offset, round(math.exp(offset) - 1.0, 4)


def availability_offset(
    announced_starters: list[dict], squad: list[dict]
) -> tuple[float, dict] | None:
    """Bounded attack offset (log-lambda units) for one team plus an explanation,
    or None when it can't be computed (no XI, or reference capacity ~ 0). ratio =
    attack_capacity(announced XI) / attack_capacity(reference XI), clamped."""
    if not announced_starters:
        return None
    reference = reference_eleven(squad)
    clamped = _clamped_offset(attack_capacity(announced_starters), attack_capacity(reference))
    if clamped is None:
        return None
    offset, delta_pct = clamped
    starting_ids = {p.get("provider_player_id") for p in announced_starters}
    missing = [p for p in reference if p.get("provider_player_id") not in starting_ids]
    missing.sort(key=_rate, reverse=True)
    explanation = {
        "attack_delta_pct": delta_pct,
        "players_out": [
            {"name": p.get("name"), "weight": round(_rate(p), 4)} for p in missing
        ],
    }
    return offset, explanation


def injury_availability_offset(
    squad: list[dict], statuses: dict[int, dict]
) -> tuple[float, dict] | None:
    """Bounded attack offset for one team from injury statuses, or None when the
    reference capacity is ~0. ``statuses`` maps provider_player_id -> {"status":
    "out"|"doubtful", "reason": str|None}; a player absent from ``statuses`` is
    fully fit. Out contributes 0.0 of its attacking weight, doubtful
    DOUBTFUL_WEIGHT, fit 1.0. The explanation lists the affected reference
    starters (by attacking weight desc) with their status + reason."""
    reference = reference_eleven(squad)

    def _mult(pid) -> float:
        s = (statuses.get(pid) or {}).get("status")
        return 0.0 if s == "out" else DOUBTFUL_WEIGHT if s == "doubtful" else 1.0

    effective = sum(_rate(p) * _mult(p.get("provider_player_id")) for p in reference)
    clamped = _clamped_offset(effective, attack_capacity(reference))
    if clamped is None:
        return None
    offset, delta_pct = clamped
    affected = [
        p for p in reference
        if (statuses.get(p.get("provider_player_id")) or {}).get("status") in ("out", "doubtful")
    ]
    affected.sort(key=_rate, reverse=True)
    explanation = {
        "attack_delta_pct": delta_pct,
        "players_out": [
            {"name": p.get("name"), "weight": round(_rate(p), 4),
             "status": (statuses.get(p.get("provider_player_id")) or {}).get("status"),
             "reason": (statuses.get(p.get("provider_player_id")) or {}).get("reason")}
            for p in affected
        ],
    }
    return offset, explanation
