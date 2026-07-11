"""Tests for the Fable-style writeup generator: four labelled sections of
deterministic prose that structurally cannot contradict the stored numbers."""
from ml.explain.writeup import WriteupInputs, build_writeup, one_in
from ml.features.build_features import MatchFeatures


def _features(**overrides) -> MatchFeatures:
    base = dict(
        elo_home=2010.0, elo_away=1890.0, elo_diff=120.0,
        strength_source_home="elo", strength_source_away="elo",
        fifa_rank_diff=10, form_home=20.0, form_away=8.0, form_diff=12.0,
        goals_for_avg_home=2.2, goals_for_avg_away=1.0, is_home_host=False,
        h2h={"matches": 5, "a_wins": 4, "draws": 1, "b_wins": 0},
        data_points_home=10, data_points_away=10,
    )
    base.update(overrides)
    return MatchFeatures(**base)


def _inputs(**overrides) -> WriteupInputs:
    base = dict(
        home_name="England", away_name="Norway",
        prob_home=0.50, prob_draw=0.26, prob_away=0.24,
        score_home=2, score_away=1, score_prob=0.11,
        stage="quarterfinal", confidence="Medium", feats=_features(),
    )
    base.update(overrides)
    return WriteupInputs(**base)


def test_returns_all_four_nonempty_sections():
    w = build_writeup(_inputs())
    assert set(w) == {"case_home", "case_away", "call", "caveat"}
    assert all(isinstance(v, str) and v for v in w.values())


def test_deterministic():
    assert build_writeup(_inputs()) == build_writeup(_inputs())


def test_call_names_the_argmax_side_and_the_scoreline():
    w = build_writeup(_inputs())
    assert w["call"].startswith("England to win")
    assert "50%" in w["call"]
    assert "2–1" in w["call"]
    assert "11%" in w["call"]


def test_call_phrases_a_draw_argmax_as_too_close_to_call():
    w = build_writeup(_inputs(prob_home=0.30, prob_draw=0.40, prob_away=0.30,
                              score_home=1, score_away=1))
    assert w["call"].startswith("Too close to call")
    assert "40%" in w["call"]


def test_caveat_states_the_actual_draw_probability():
    w = build_writeup(_inputs())
    assert "26%" in w["caveat"]
    assert "one in 4" in w["caveat"]
    # Knockout stage → extra-time framing.
    assert "extra time" in w["caveat"].lower()


def test_caveat_flags_open_games_and_thin_data():
    w = build_writeup(_inputs(prob_home=0.40, prob_draw=0.30, prob_away=0.30,
                              confidence="Low", stage="group"))
    assert "open game" in w["caveat"]
    assert "thin" in w["caveat"]


def test_knockout_block_adds_advance_odds_to_the_call():
    ko = {"p_advance_home": 0.58, "p_advance_away": 0.42,
          "p_extra_time": 0.26, "p_shootout": 0.12,
          "paths": {"home": {"win_90": 0.5, "win_et": 0.05, "win_pens": 0.03},
                    "away": {"win_90": 0.24, "win_et": 0.1, "win_pens": 0.08}}}
    w = build_writeup(_inputs(knockout=ko))
    assert "58%" in w["call"]
    assert "England advance" in w["call"]


def test_market_agreement_lands_in_the_favourites_case():
    w = build_writeup(_inputs(market=(0.52, 0.26, 0.22)))
    assert "market agrees" in w["case_home"]
    assert "market agrees" not in w["case_away"]


def test_opponent_absences_strengthen_the_other_sides_case():
    w = build_writeup(_inputs(players_out_away=["Quansah", "Guehi"]))
    assert "Quansah" in w["case_home"]
    assert "Quansah" not in w["case_away"]


def test_none_on_thin_inputs_and_never_raises():
    assert build_writeup(_inputs(score_home=None, score_away=None, score_prob=None)) is None
    # Degenerate but non-None inputs must still produce text, not raise.
    bare = _inputs(feats=_features(form_diff=None, goals_for_avg_home=None,
                                   goals_for_avg_away=None,
                                   h2h={"matches": 0, "a_wins": 0, "draws": 0, "b_wins": 0}))
    assert build_writeup(bare) is not None


def test_one_in_phrasing():
    assert one_in(0.26) == "roughly one in 4"
    assert one_in(0.5) == "roughly one in 2"
    assert one_in(0.0) == "next to no chance"
