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
    text = _preview(predicted_margin=-3.2)
    p3 = text.split("\n\n")[2]
    assert "Eels by 3.2" in p3


def test_zero_margin_reads_as_dead_level():
    text = _preview(predicted_margin=0.0)
    p3 = text.split("\n\n")[2]
    assert "dead-level" in p3
