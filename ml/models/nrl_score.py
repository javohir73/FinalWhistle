"""Leak-free, fixture-specific NRL scoreline model.

The old ``nrl_margin_total`` model returned one league-wide expected total for
every fixture.  This model keeps exponentially weighted attack and defence
states per team, combines them with the league's current home/away scoring
pace, and selects a plausible exact scoreline from an empirical score prior.

External inputs are deliberately optional and pre-match-only.  They provide a
stable contract for future market, team-list/injury, and weather capture while
the model remains useful (and fully testable) with historical results alone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class NrlScoreParams:
    version: str = "nrl-score-v0.1-shadow"
    alpha: float = 0.05
    attack_weight: float = 0.55
    defence_weight: float = 0.25
    prior_games: float = 10.0
    initial_home_mean: float = 22.0
    initial_away_mean: float = 20.0
    market_weight: float = 0.70
    score_sigma: float = 8.5
    empirical_weight: float = 0.35
    max_score: int = 70
    baseline_total: float = 47.093590784472916
    promotion_improvement: float = 0.05


@dataclass(frozen=True)
class NrlExternalScoreSignals:
    """Signals captured before kickoff; all values are optional.

    Point adjustments are intentionally generic so a later, evidence-backed
    team-list/injury model can supply them without coupling this pure model to
    a specific provider. ``total_adjustment`` is the weather-style game-wide
    adjustment. Market inputs blend with, rather than silently replace, the
    independent model.
    """

    market_total: float | None = None
    market_margin: float | None = None  # home minus away
    home_points_adjustment: float = 0.0
    away_points_adjustment: float = 0.0
    total_adjustment: float = 0.0


@dataclass
class NrlScoreState:
    params: NrlScoreParams = field(default_factory=NrlScoreParams)
    global_home: float | None = None
    global_away: float | None = None
    attack: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    games: dict[int, int] = field(default_factory=dict)
    score_counts: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.global_home is None:
            self.global_home = self.params.initial_home_mean
        if self.global_away is None:
            self.global_away = self.params.initial_away_mean

    @property
    def league_team_mean(self) -> float:
        return (float(self.global_home) + float(self.global_away)) / 2.0

    def _shrunk(self, values: dict[int, float], team_id: int) -> float:
        league = self.league_team_mean
        count = self.games.get(team_id, 0)
        value = values.get(team_id, league)
        prior = self.params.prior_games
        return (count * value + prior * league) / (count + prior)

    def expected_scores(self, home_team_id: int, away_team_id: int) -> tuple[float, float]:
        p = self.params
        league = self.league_team_mean
        home_attack = self._shrunk(self.attack, home_team_id)
        home_defence = self._shrunk(self.defence, home_team_id)
        away_attack = self._shrunk(self.attack, away_team_id)
        away_defence = self._shrunk(self.defence, away_team_id)
        home = (
            float(self.global_home)
            + p.attack_weight * (home_attack - league)
            + p.defence_weight * (away_defence - league)
        )
        away = (
            float(self.global_away)
            + p.attack_weight * (away_attack - league)
            + p.defence_weight * (home_defence - league)
        )
        return max(0.0, home), max(0.0, away)

    def update(
        self,
        home_team_id: int,
        away_team_id: int,
        score_home: int,
        score_away: int,
    ) -> None:
        """Advance state after a finished match. Prediction must happen first."""
        alpha = self.params.alpha
        league = self.league_team_mean
        self.global_home = (1 - alpha) * float(self.global_home) + alpha * score_home
        self.global_away = (1 - alpha) * float(self.global_away) + alpha * score_away
        for team_id, scored, allowed in (
            (home_team_id, score_home, score_away),
            (away_team_id, score_away, score_home),
        ):
            self.attack[team_id] = (
                (1 - alpha) * self.attack.get(team_id, league) + alpha * scored
            )
            self.defence[team_id] = (
                (1 - alpha) * self.defence.get(team_id, league) + alpha * allowed
            )
            self.games[team_id] = self.games.get(team_id, 0) + 1
            if 0 <= scored <= self.params.max_score:
                self.score_counts[scored] = self.score_counts.get(scored, 0) + 1


@dataclass(frozen=True)
class NrlScorePrediction:
    expected_home: float
    expected_away: float
    predicted_home: int
    predicted_away: int
    model_version: str

    @property
    def expected_total(self) -> float:
        return self.expected_home + self.expected_away

    @property
    def expected_margin(self) -> float:
        return self.expected_home - self.expected_away


def build_score_state(
    matches: Iterable,
    params: NrlScoreParams | None = None,
) -> NrlScoreState:
    """Replay finished match-like objects in their supplied order."""
    state = NrlScoreState(params=params or NrlScoreParams())
    for match in matches:
        if (
            match.home_team_id is None
            or match.away_team_id is None
            or match.score_home is None
            or match.score_away is None
        ):
            continue
        state.update(
            match.home_team_id,
            match.away_team_id,
            int(match.score_home),
            int(match.score_away),
        )
    return state


def _score_distribution(mean: float, state: NrlScoreState) -> list[float]:
    """Normalized discrete distribution with an empirical NRL score prior."""
    p = state.params
    total_observed = sum(state.score_counts.values())
    categories = p.max_score + 1
    raw: list[float] = []
    for score in range(categories):
        gaussian = math.exp(-0.5 * ((score - mean) / p.score_sigma) ** 2)
        empirical = (state.score_counts.get(score, 0) + 1.0) / (
            total_observed + categories
        )
        raw.append(gaussian * empirical ** p.empirical_weight)
    mass = sum(raw) or 1.0
    return [value / mass for value in raw]


def _consistent_scoreline(
    expected_home: float,
    expected_away: float,
    state: NrlScoreState,
) -> tuple[int, int]:
    """Most likely pair constrained to sum to the rounded expected total."""
    target_total = max(0, min(2 * state.params.max_score, round(expected_home + expected_away)))
    home_dist = _score_distribution(expected_home, state)
    away_dist = _score_distribution(expected_away, state)
    best_pair = (round(expected_home), round(expected_away))
    best_log_prob = -math.inf
    lower = max(0, target_total - state.params.max_score)
    upper = min(state.params.max_score, target_total)
    for home_score in range(lower, upper + 1):
        away_score = target_total - home_score
        log_prob = math.log(max(home_dist[home_score], 1e-300)) + math.log(
            max(away_dist[away_score], 1e-300)
        )
        if log_prob > best_log_prob:
            best_log_prob = log_prob
            best_pair = (home_score, away_score)
    return best_pair


def predict_scoreline(
    state: NrlScoreState,
    home_team_id: int,
    away_team_id: int,
    signals: NrlExternalScoreSignals | None = None,
) -> NrlScorePrediction:
    signals = signals or NrlExternalScoreSignals()
    p = state.params
    home, away = state.expected_scores(home_team_id, away_team_id)
    home += signals.home_points_adjustment + signals.total_adjustment / 2.0
    away += signals.away_points_adjustment + signals.total_adjustment / 2.0
    home = max(0.0, home)
    away = max(0.0, away)

    internal_total = max(home + away, 1e-9)
    if signals.market_total is not None and signals.market_total > 0:
        blended_total = (
            (1 - p.market_weight) * internal_total + p.market_weight * signals.market_total
        )
        scale = blended_total / internal_total
        home *= scale
        away *= scale

    if signals.market_margin is not None:
        total = home + away
        margin = (1 - p.market_weight) * (home - away) + p.market_weight * signals.market_margin
        home = min(total, max(0.0, (total + margin) / 2.0))
        away = total - home

    predicted_home, predicted_away = _consistent_scoreline(home, away, state)
    return NrlScorePrediction(
        expected_home=home,
        expected_away=away,
        predicted_home=predicted_home,
        predicted_away=predicted_away,
        model_version=p.version,
    )
