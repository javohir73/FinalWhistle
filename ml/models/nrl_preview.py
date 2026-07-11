"""Deterministic prose preview generator for the NRL Match Intelligence page
(Wave 1). No LLM at runtime -- three short paragraphs built purely from the
model's own numbers (favourite + probability, Elo gap, form lines, predicted
margin/total). Regenerated every nrl_predict --generate run and stamped onto
SportPrediction.preview_text (see pipeline/sports/nrl_predict.py).
"""
from __future__ import annotations


def build_preview(
    *,
    home: str,
    away: str,
    p_home: float,
    p_away: float,
    elo_home: float,
    elo_away: float,
    home_form_summary: str,
    away_form_summary: str,
    predicted_margin: float,
    predicted_total: float,
) -> str:
    """Three short paragraphs, joined by a blank line. Pure function of the
    inputs -- no DB/network access, so it's trivially unit-testable and safe
    to call from any pipeline step."""
    favourite = home if p_home >= p_away else away
    fav_prob = max(p_home, p_away)
    elo_gap = abs(elo_home - elo_away)
    elo_leader = home if elo_home >= elo_away else away
    elo_trailer = away if elo_leader == home else home

    p1 = (
        f"{favourite} are the model's pick, given a {round(fav_prob * 100)}% "
        f"chance heading into this one."
    )
    p2 = (
        f"{elo_leader} carry the bigger Elo rating, {round(elo_gap)} points clear "
        f"of {elo_trailer}. {home}: {home_form_summary}. {away}: {away_form_summary}."
    )
    side = home if predicted_margin > 0 else away if predicted_margin < 0 else None

    # The win-probability favourite (above) and the margin regression's sign
    # are two independently fitted models -- in a narrow Elo band they can
    # pick opposite sides. When that happens, don't let paragraph 3 credit a
    # lead the favourite doesn't actually have; read the margin as neutral
    # instead. Doesn't fire on the margin==0 case (side is already None
    # there, already neutral) or on the overwhelmingly common case where the
    # two models agree.
    if side is not None and side != favourite:
        p3 = (
            f"The margin model reads this as line-ball -- {abs(round(predicted_margin, 1))} "
            f"points in it either way, with a total of {round(predicted_total)} points "
            f"across both sides."
        )
    else:
        margin_txt = (
            f"{side} by {abs(round(predicted_margin, 1))}" if side else "a dead-level margin"
        )
        p3 = (
            f"The model's number: {margin_txt}, with a total of "
            f"{round(predicted_total)} points across both sides."
        )
    return "\n\n".join([p1, p2, p3])
