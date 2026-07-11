"""Fable-style match writeup: four labelled sections of deterministic prose.

Presentation only. Every sentence is templated from a model field, so the text
can never disagree with the numbers it rides with — the model stays the brain,
this is the voice (spec: docs/superpowers/specs/
2026-07-11-wc26-writeup-and-signal-readiness-design.md). Pure function of its
inputs: no LLM, no randomness, no clock, no DB. Missing signals drop their
sentence; inputs too thin to say anything honest return None (the frontend
hides the section).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ml.features.build_features import MatchFeatures


def one_in(p: float) -> str:
    """'roughly one in N' for a probability (N = round(1/p))."""
    if p <= 0:
        return "next to no chance"
    return f"roughly one in {max(1, round(1 / p))}"


def _pct(p: float) -> str:
    # Half-up like the frontend's Math.round — prose and probability bar must
    # never disagree on the same stored value.
    return f"{int(math.floor(p * 100 + 0.5))}%"


@dataclass(frozen=True)
class WriteupInputs:
    """Everything build_payload already computes, as plain values."""
    home_name: str
    away_name: str
    prob_home: float
    prob_draw: float
    prob_away: float
    score_home: int | None
    score_away: int | None
    score_prob: float | None
    stage: str                      # "group" or a knockout stage
    confidence: str                 # "High" | "Medium" | "Low"
    feats: MatchFeatures
    knockout: dict | None = None    # ml/models/knockout.py to_payload() shape
    market: tuple[float, float, float] | None = None  # implied (H, D, A) triple
    players_out_home: list[str] = field(default_factory=list)
    players_out_away: list[str] = field(default_factory=list)


def build_writeup(w: WriteupInputs) -> dict | None:
    """The four sections, or None when the prediction is too thin to narrate."""
    if w.score_home is None or w.score_away is None or w.score_prob is None:
        return None
    return {
        "case_home": _case(w, side="home"),
        "case_away": _case(w, side="away"),
        "call": _call(w),
        "caveat": _caveat(w),
    }


def _case(w: WriteupInputs, side: str) -> str:
    """One side's argument: a guaranteed probability sentence, then evidence in
    PRIORITY order — the match-specific signals (opponent absences, market
    lean) outrank the structural edges (Elo, form, goals, history, host),
    because the structural ones already live in the reasons list. Capped at 4
    sentences total, so priority decides what survives, not template order."""
    name = w.home_name if side == "home" else w.away_name
    opp = w.away_name if side == "home" else w.home_name
    p_win = w.prob_home if side == "home" else w.prob_away
    f = w.feats
    sentences = [f"The model gives {name} a {_pct(p_win)} chance of winning in 90 minutes."]

    elo_edge = f.elo_diff if side == "home" else -f.elo_diff
    if elo_edge >= 20:
        own = f.elo_home if side == "home" else f.elo_away
        other = f.elo_away if side == "home" else f.elo_home
        strength = "clearly the stronger side" if elo_edge >= 150 else "the stronger side"
        sentences.append(f"{name} rate as {strength} on Elo ({own:.0f} vs {other:.0f}).")

    opp_out = w.players_out_away if side == "home" else w.players_out_home
    if opp_out:
        listed = ", ".join(opp_out[:3])
        sentences.append(f"{opp}'s problems help the case — they are missing {listed}.")

    if w.market is not None:
        m_idx = max(range(3), key=lambda i: w.market[i])  # 0=H 1=D 2=A
        if m_idx == (0 if side == "home" else 2):
            sentences.append(
                f"The betting market agrees, making {name} favourites at {_pct(w.market[m_idx])}.")

    if f.form_diff is not None:
        form_edge = f.form_diff if side == "home" else -f.form_diff
        if form_edge >= 2:
            sentences.append(f"{name} also arrive in the better recent form.")

    if f.goals_for_avg_home is not None and f.goals_for_avg_away is not None:
        own_avg = f.goals_for_avg_home if side == "home" else f.goals_for_avg_away
        opp_avg = f.goals_for_avg_away if side == "home" else f.goals_for_avg_home
        if own_avg - opp_avg >= 0.5:
            sentences.append(
                f"They have been scoring more freely — {own_avg:.1f} a game to {opp}'s {opp_avg:.1f}.")

    own_wins = f.h2h["a_wins"] if side == "home" else f.h2h["b_wins"]
    opp_wins = f.h2h["b_wins"] if side == "home" else f.h2h["a_wins"]
    if f.h2h["matches"] > 0 and own_wins > opp_wins:
        sentences.append(
            f"History leans their way too: {own_wins} wins in the last {f.h2h['matches']} meetings.")

    if side == "home" and f.is_home_host:
        sentences.append(f"And {name} play this one at home as a tournament host.")

    return " ".join(sentences[:4])


def _call(w: WriteupInputs) -> str:
    """The headline: always the argmax outcome, so it structurally cannot
    contradict the served triple; the scoreline is the grid's own argmax and is
    reported as such (it may legitimately differ from the W/D/L lean)."""
    probs = {"home": w.prob_home, "draw": w.prob_draw, "away": w.prob_away}
    top = max(probs, key=lambda k: probs[k])
    score = f"{w.score_home}–{w.score_away}"
    if top == "draw":
        text = (f"Too close to call — the draw is the single most likely outcome at "
                f"{_pct(w.prob_draw)}, and {score} the most likely scoreline "
                f"(about {_pct(w.score_prob)}).")
    else:
        winner = w.home_name if top == "home" else w.away_name
        text = (f"{winner} to win — {_pct(probs[top])} in 90 minutes, with {score} the "
                f"single most likely scoreline (about {_pct(w.score_prob)}).")
    if w.knockout:
        adv_h = w.knockout["p_advance_home"]
        adv_a = w.knockout["p_advance_away"]
        favored, p_adv = (w.home_name, adv_h) if adv_h >= adv_a else (w.away_name, adv_a)
        text += (f" Over the full tie, {favored} advance in {_pct(p_adv)} of simulations, "
                 f"and there is a {_pct(w.knockout['p_extra_time'])} chance it goes past 90 minutes.")
    return text


def _caveat(w: WriteupInputs) -> str:
    """The honest bit: the draw stated plainly, openness, the upset chance,
    and a thin-data warning whenever confidence is Low."""
    if w.stage != "group":
        sentences = [
            f"A draw after 90 minutes is live at {one_in(w.prob_draw)} ({_pct(w.prob_draw)}), "
            f"so extra time or penalties would not shock."]
    else:
        sentences = [f"The draw is live at {one_in(w.prob_draw)} ({_pct(w.prob_draw)})."]
    if max(w.prob_home, w.prob_draw, w.prob_away) < 0.45:
        sentences.append("No outcome clears 45% — this is a genuinely open game.")
    underdog, p_up = ((w.away_name, w.prob_away) if w.prob_home >= w.prob_away
                      else (w.home_name, w.prob_home))
    sentences.append(f"{underdog} win outright in {_pct(p_up)} of the model's scenarios.")
    if w.confidence == "Low":
        sentences.append("The data behind this one is thin, so treat the numbers with extra care.")
    return " ".join(sentences)
