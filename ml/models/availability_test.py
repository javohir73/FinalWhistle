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


from ml.models.availability import DOUBTFUL_WEIGHT, injury_availability_offset


def _sq():
    # Elite striker (pid 1) + 10 ordinary regulars, all full-season minutes.
    return [_p(1, "F", 25, 2700, name="Star")] + [_p(i, "M", 2, 2700) for i in range(2, 12)]


def test_injury_out_removes_full_weight():
    squad = _sq()
    off, expl = injury_availability_offset(squad, {1: {"status": "out", "reason": "Calf"}})
    assert off < 0.0
    assert {"name": "Star", "weight": expl["players_out"][0]["weight"],
            "status": "out", "reason": "Calf"} == expl["players_out"][0]
    assert expl["attack_delta_pct"] == round(math.exp(off) - 1.0, 4)


def test_injury_doubtful_is_half_of_out():
    squad = _sq()
    # Injure a mid-tier regular (pid 2), NOT the dominant striker — otherwise both
    # offsets saturate the -0.25 clamp and the inequality can't be observed.
    off_out, _ = injury_availability_offset(squad, {2: {"status": "out", "reason": None}})
    off_dbt, _ = injury_availability_offset(squad, {2: {"status": "doubtful", "reason": None}})
    assert off_out < off_dbt < 0.0  # doubtful cuts less than out, neither clamped


def test_injury_no_injuries_is_zero_offset():
    off, expl = injury_availability_offset(_sq(), {})
    assert off == 0.0
    assert expl["players_out"] == []


def test_injury_offset_clamped_low():
    squad = _sq()
    statuses = {i: {"status": "out", "reason": None} for i in range(1, 12)}  # whole XI out
    off, _ = injury_availability_offset(squad, statuses)
    assert off == ATTACK_OFFSET_LO


def test_injury_player_not_in_reference_has_no_effect():
    squad = _sq()
    off, expl = injury_availability_offset(squad, {999: {"status": "out", "reason": "x"}})
    assert off == 0.0 and expl["players_out"] == []


def test_injury_none_when_empty_squad():
    assert injury_availability_offset([], {1: {"status": "out", "reason": None}}) is None


def test_doubtful_weight_default():
    assert DOUBTFUL_WEIGHT == 0.5
