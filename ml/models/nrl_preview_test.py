"""Tests for the deterministic NRL prose preview generator (no LLM at
runtime -- pure string formatting from model numbers)."""
from ml.models.nrl_preview import build_preview


def _preview(**overrides):
    base = dict(
        home="Storm", away="Eels", p_home=0.63, p_away=0.37,
        elo_home=1560.0, elo_away=1490.0,
        home_form_summary="4W-1L in their last 5",
        away_form_summary="2W-3L in their last 5",
        predicted_margin=6.5, predicted_total=41.0,
    )
    base.update(overrides)
    return build_preview(**base)


def test_returns_three_paragraphs():
    text = _preview()
    paragraphs = text.split("\n\n")
    assert len(paragraphs) == 3


def test_names_the_favourite_and_probability():
    text = _preview()
    assert "Storm" in text.split("\n\n")[0]
    assert "63%" in text.split("\n\n")[0]


def test_names_the_elo_leader_and_gap():
    text = _preview()
    assert "70" in text.split("\n\n")[1]  # 1560 - 1490
    assert "Storm" in text.split("\n\n")[1]


def test_includes_both_form_summaries():
    text = _preview()
    p2 = text.split("\n\n")[1]
    assert "4W-1L in their last 5" in p2
    assert "2W-3L in their last 5" in p2


def test_margin_and_total_paragraph():
    text = _preview()
    p3 = text.split("\n\n")[2]
    assert "Storm by 6.5" in p3
    assert "41" in p3


def test_negative_margin_credits_the_away_side():
    # p_home/p_away flipped from the module default so Eels are also the
    # win-prob favourite here -- the two models must AGREE for paragraph 3 to
    # credit a side (see the disagreement tests below); the base fixture's
    # p_home=0.63 favours Storm, which would make this a disagreement case
    # instead of a same-side agreement case.
    text = _preview(p_home=0.37, p_away=0.63, predicted_margin=-3.2)
    p3 = text.split("\n\n")[2]
    assert "Eels by 3.2" in p3


def test_zero_margin_reads_as_dead_level():
    text = _preview(predicted_margin=0.0)
    p3 = text.split("\n\n")[2]
    assert "dead-level" in p3


# ---- favourite / margin-sign disagreement (review finding 1) ----
#
# p_home/p_away (the Elo win-prob model) and predicted_margin (an
# independently fitted margin regression) can pick opposite sides in a
# narrow Elo band -- e.g. under the v0.1 fallback params, an away team ~50-89
# Elo points ahead is still behind on home-ground-adjusted win probability
# but already ahead on the margin regression. When that happens neither side
# should be credited a lead in paragraph 3.

def test_disagreeing_favourite_and_margin_sign_reads_neutral():
    text = _preview(p_home=0.4869, p_away=0.5131, predicted_margin=1.8, predicted_total=41.0)
    p3 = text.split("\n\n")[2]
    assert "Storm" not in p3
    assert "Eels" not in p3
    assert "1.8" in p3
    assert "41" in p3


def test_agreement_case_matches_pinned_expected_text():
    """Byte-identical pin for the (overwhelmingly common) case where the
    win-prob favourite and the margin regression's sign agree -- reuses the
    exact fixture and expected substrings from test_margin_and_total_paragraph
    so this fix can't silently reword the common path."""
    text = _preview()
    p3 = text.split("\n\n")[2]
    assert p3 == "The model's number: Storm by 6.5, with a total of 41 points across both sides."
