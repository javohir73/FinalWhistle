import math

from ml.models.goalscorers import goalscorers, player_rate, squad_minutes_weight


def _p(pid, name, pos, cg, cm, wg, wm, status=None):
    return {"provider_player_id": pid, "name": name, "position": pos,
            "club_goals": cg, "club_minutes": cm, "wc_goals": wg, "wc_minutes": wm,
            "lineup_status": status}


def test_player_rate_blends_form_and_position_prior():
    # a striker with 20 club goals in ~2700 min (30 nineties): pulled toward ~0.66/90
    high = player_rate(20, 2700, 0, 0, "F")
    # a striker with no minutes -> pure position prior 0.45
    cold = player_rate(0, 0, 0, 0, "F")
    assert abs(cold - 0.45) < 1e-9
    assert 0.5 < high < 0.7


def test_squad_minutes_weight_clamps():
    assert squad_minutes_weight(3000, 0) == 1.0
    assert squad_minutes_weight(6000, 0) == 1.0
    assert squad_minutes_weight(600, 0) == 0.2
    assert squad_minutes_weight(0, 0) == 0.0


def test_goalscorers_xg_sums_to_lambda_and_is_sorted():
    players = [
        _p(1, "Striker", "F", 18, 2700, 2, 270, "starter"),
        _p(2, "Mid", "M", 6, 2700, 0, 270, "starter"),
        _p(3, "Defender", "D", 1, 2700, 0, 270, "starter"),
    ]
    out = goalscorers(2.0, players, "lineup")
    assert abs(sum(r["xg"] for r in out) - 2.0) < 1e-3      # conserves team lambda
    assert out[0]["name"] == "Striker"                       # sorted by xg desc
    assert out[0]["p_score"] == round(1 - math.exp(-out[0]["xg"]), 4)
    assert all(r["p_score"] >= r["p_score_2plus"] for r in out)


def test_lineup_mode_excludes_not_listed_players():
    players = [
        _p(1, "Starter", "F", 10, 2000, 1, 200, "starter"),
        _p(2, "Benched", "F", 12, 2000, 1, 200, "sub"),
        _p(3, "NotListed", "F", 15, 2000, 1, 200, None),
    ]
    out = goalscorers(2.0, players, "lineup")
    names = {r["name"] for r in out}
    assert "NotListed" not in names          # mins weight 0 -> omitted
    assert {"Starter", "Benched"} <= names


def test_returns_empty_when_total_weight_zero():
    assert goalscorers(2.0, [_p(1, "X", "G", 0, 0, 0, 0, None)], "lineup") == []
