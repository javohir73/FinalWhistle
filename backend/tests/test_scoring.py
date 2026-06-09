"""Unit tests for backend-owned bracket scoring."""
from app.scoring import score_bracket, FINAL_NO


def test_points_breakdown_matches_rules():
    group_picks = {1: "home", 2: "draw", 3: "away", 4: "home"}
    group_results = {1: "home", 2: "draw", 3: "home", 4: "home"}  # 3 of 4 correct
    knockout_picks = {
        73: 10, 89: 10, 97: 10,  # R32/R16/QF correct (5 each)
        101: 20,                 # SF correct -> finalist (10)
        FINAL_NO: 20,            # final correct -> champion (20)
    }
    knockout_results = {73: 10, 89: 10, 97: 99, 101: 20, FINAL_NO: 20}  # QF (97) wrong

    s = score_bracket(group_picks, group_results, knockout_picks, knockout_results)
    assert s["group_points"] == 9            # 3 correct * 3
    assert s["knockout_points"] == 5 + 5 + 10  # R32 + R16 correct (5,5), QF wrong, SF correct (10)
    assert s["champion_bonus"] == 20
    assert s["total_points"] == 9 + 20 + 20


def test_no_results_scores_zero():
    s = score_bracket({1: "home"}, {}, {73: 5, FINAL_NO: 9}, {})
    assert s == {"group_points": 0, "knockout_points": 0, "champion_bonus": 0, "total_points": 0}


def test_unpicked_unplayed_never_scores():
    # No picks, no results -> must be 0 (guards None == None false-positives).
    s = score_bracket({}, {1: "home"}, {}, {FINAL_NO: 7})
    assert s["total_points"] == 0
