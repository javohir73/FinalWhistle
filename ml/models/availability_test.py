# ml/models/availability_test.py
"""Unit tests for the pure availability core (announced-XI attack adjustment)."""
import math

from ml.models.availability import (
    ATTACK_OFFSET_HI, ATTACK_OFFSET_LO, attack_capacity, availability_offset,
    reference_eleven,
)


def _p(pid, pos, cg, cm, wg=0, wm=0, name=None):
    return {"provider_player_id": pid, "name": name or f"p{pid}", "position": pos,
            "club_goals": cg, "club_minutes": cm, "wc_goals": wg, "wc_minutes": wm}


def _squad_11():
    # 1 elite striker + 10 ordinary regulars, all full-season minutes.
    return [_p(1, "F", 25, 2700, name="Star")] + [
        _p(i, "M" if i < 8 else "D", 2, 2700) for i in range(2, 12)
    ]


def test_full_strength_xi_has_zero_offset():
    squad = _squad_11()
    offset, expl = availability_offset(squad, squad)  # announced == usual XI
    assert offset == 0.0
    assert expl["attack_delta_pct"] == 0.0
    assert expl["players_out"] == []


def test_missing_striker_gives_negative_offset_and_names_him():
    squad = _squad_11() + [_p(99, "F", 0, 300, name="Sub")]  # a weak deputy
    # Announced XI = the ten regulars + the weak deputy (Star benched).
    announced = [p for p in squad if p["provider_player_id"] not in (1,)][:11]
    offset, expl = availability_offset(announced, squad)
    assert offset < 0.0
    assert expl["attack_delta_pct"] == round(math.exp(offset) - 1.0, 4)
    assert "Star" in {p["name"] for p in expl["players_out"]}


def test_offset_is_clamped_low():
    squad = [_p(1, "F", 40, 2700, name="Star")] + [_p(i, "D", 0, 2700) for i in range(2, 12)]
    weak = [_p(500 + i, "G", 0, 200) for i in range(11)]  # a keeper-only XI
    offset, _ = availability_offset(weak, squad)
    assert offset == ATTACK_OFFSET_LO


def test_offset_capped_when_xi_stronger_than_usual():
    squad = [_p(i, "D", 0, 2700) for i in range(1, 12)] + [_p(50, "F", 30, 400, name="WonderKid")]
    strong = [_p(50, "F", 30, 400, name="WonderKid")] + [_p(i, "D", 0, 2700) for i in range(1, 11)]
    offset, _ = availability_offset(strong, squad)
    assert offset <= ATTACK_OFFSET_HI


def test_reference_eleven_picks_top_by_minutes():
    squad = [_p(i, "M", 1, i * 100) for i in range(1, 15)]  # 14 players, ascending minutes
    ref = reference_eleven(squad)
    assert len(ref) == 11
    assert {p["provider_player_id"] for p in ref} == set(range(4, 15))  # top 11 by minutes


def test_none_when_no_announced_xi():
    assert availability_offset([], _squad_11()) is None


def test_none_when_squad_empty():
    assert availability_offset(_squad_11(), []) is None


def test_attack_capacity_is_positive_for_nonempty():
    assert attack_capacity([_p(1, "F", 10, 900)]) > 0.0
