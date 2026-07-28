import pytest

from pipeline.p4_gate import classify_group, select_branch


@pytest.mark.parametrize("ci,expected", [
    ([-.1, -.001], "beating"), ([.001, .1], "beaten"),
    ([-.1, 0], "inconclusive"), ([0, .1], "inconclusive"),
])
def test_ci_rule_is_mechanical(ci, expected):
    assert classify_group({"status": "ready", "diff_ci95": ci}) == expected


def test_only_credible_model_win_selects_p5b():
    base = {"venue": "kalshi", "market_type": "match_winner", "horizon": "60-75", "status": "ready"}
    beating = select_branch({"groups": [{**base, "diff_ci95": [-.2, -.01]}]}, venue="kalshi", market_type="match_winner", horizon="60-75")
    inconclusive = select_branch({"groups": [{**base, "diff_ci95": [-.01, .01]}]}, venue="kalshi", market_type="match_winner", horizon="60-75")
    assert beating["selected_branch"] == "P5B"
    assert inconclusive["selected_branch"] == "P5A"


def test_insufficient_data_selects_no_branch():
    decision = select_branch({"groups": []}, venue="kalshi", market_type="match_winner", horizon="60-75")
    assert decision == {"verdict": "insufficient", "selected_branch": None, "reason": "precommitted comparison group missing or non-unique"}
