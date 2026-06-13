"""Pydantic response schemas. The PredictionOut shape is the PRD §17 contract
that the frontend consumes."""
from __future__ import annotations

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str
    app: str
    model_version: str


class TeamsOut(BaseModel):
    home: str
    away: str


class ProbabilitiesOut(BaseModel):
    home_win: float
    draw: float
    away_win: float


class PredictedScoreOut(BaseModel):
    home: int | None
    away: int | None
    probability: float | None


class FeatureWeightOut(BaseModel):
    name: str
    weight: float


class HeadToHeadOut(BaseModel):
    matches: int
    home_wins: int
    draws: int
    away_wins: int


class OddsComparisonOut(BaseModel):
    available: bool = False


class PredictionOut(BaseModel):
    """PRD §17 prediction contract."""

    match_id: int
    model_version: str
    generated_at: str | None
    teams: TeamsOut
    home_team_id: int | None = None
    away_team_id: int | None = None
    group: str | None = None
    group_id: int | None = None
    stage: str | None = None
    is_neutral: bool
    kickoff_utc: str | None = None
    venue: str | None = None
    venue_city: str | None = None
    venue_country: str | None = None
    probabilities: ProbabilitiesOut
    predicted_score: PredictedScoreOut
    confidence: str | None
    reasons: list[str]
    top_features: list[FeatureWeightOut]
    head_to_head: HeadToHeadOut
    odds_comparison: OddsComparisonOut
    disclaimer: str


class TeamOut(BaseModel):
    id: int
    name: str
    country_code: str | None
    confederation: str | None
    fifa_rank: int | None
    elo_rating: float | None
    is_host: bool


class MatchSummaryOut(BaseModel):
    match_id: int
    stage: str
    group: str | None
    kickoff_utc: str | None
    venue: str | None
    venue_city: str | None
    venue_country: str | None
    is_neutral: bool
    status: str
    score_home: int | None
    score_away: int | None
    minute: int | None
    teams: TeamsOut
    predicted_winner: str | None
    probabilities: ProbabilitiesOut | None
    predicted_score: PredictedScoreOut | None
    confidence: str | None


class StandingRowOut(BaseModel):
    """A projected (not played) final-table row from the group Monte-Carlo."""

    team_id: int
    team: str
    projected_points: int
    projected_goals_for: int
    projected_goal_diff: int
    qualification_prob: float | None


class GroupOut(BaseModel):
    id: int
    name: str
    standings: list[StandingRowOut]


class TournamentOddsOut(BaseModel):
    """Per-team knockout-run probabilities from the tournament Monte-Carlo."""

    team_id: int
    team: str
    make_knockout: float | None
    reach_r16: float | None
    reach_qf: float | None
    reach_sf: float | None
    reach_final: float | None
    win_title: float | None


class FormResultOut(BaseModel):
    opponent: str
    score_for: int
    score_against: int
    result: str  # W/D/L
    date: str | None


class TeamProfileOut(BaseModel):
    team: TeamOut
    group_id: int | None = None
    group_name: str | None = None
    recent_form: list[FormResultOut]
    strengths: list[str]
    weaknesses: list[str]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    error: ErrorBody


# ---- Auth (first-party email + password) ----
class RegisterIn(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str | None = None
    avatar_url: str | None = None


# ---- Accounts / brackets / leaderboard ----
class GroupPickIn(BaseModel):
    match_id: int
    pick: str  # home/draw/away


class KnockoutPickIn(BaseModel):
    match_no: int
    picked_team_id: int


class BracketIn(BaseModel):
    group_picks: list[GroupPickIn] = []
    knockout_picks: list[KnockoutPickIn] = []
    champion_team_id: int | None = None
    encoded_state: str | None = None


class BracketScoreOut(BaseModel):
    group_points: int
    knockout_points: int
    champion_bonus: int
    total_points: int
    rank: int | None = None


class BracketOut(BaseModel):
    id: int
    visibility: str
    display_name: str | None = None
    champion_team_id: int | None = None
    completion_pct: float
    group_picks: list[GroupPickIn]
    knockout_picks: list[KnockoutPickIn]
    score: BracketScoreOut | None = None
    submitted_at: str | None = None
    updated_at: str | None = None


# ---- Per-match picks (account copy of the device-local match predictions) ----
class MatchPickIn(BaseModel):
    match_id: int
    pick: str  # home/draw/away


class MatchPicksIn(BaseModel):
    picks: list[MatchPickIn] = []


class MatchPicksOut(BaseModel):
    picks: list[MatchPickIn]
    updated_at: str | None = None


class JoinLeaderboardIn(BaseModel):
    display_name: str
    visibility: str = "public"  # public/private


class LeaderboardRowOut(BaseModel):
    rank: int | None = None
    display_name: str
    champion: str | None = None
    total_points: int
    percentile: int | None = None
    updated_at: str | None = None
