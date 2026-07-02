"""SQLAlchemy ORM models for the MVP tables (PRD §10).

Kept deliberately DB-agnostic (generic JSON, String for enums) so the same
models run on SQLite in tests and PostgreSQL in production. Phase 2+ tables
(players, injuries, live_events, social_sentiment, simulations) are added in
their own phases.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    year: Mapped[int] = mapped_column(Integer)
    host_countries: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    groups: Mapped[list[Group]] = relationship(back_populates="tournament")
    matches: Mapped[list[Match]] = relationship(back_populates="tournament")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(3))
    confederation: Mapped[str | None] = mapped_column(String(20))
    fifa_rank: Mapped[int | None] = mapped_column(Integer)
    elo_rating: Mapped[float | None] = mapped_column(Float)
    flag_url: Mapped[str | None] = mapped_column(String(300))
    is_host: Mapped[bool] = mapped_column(default=False)
    # API-Football team id (api-sports.io), linked by normalized name. Lets the
    # goalscorer ingestion pull this team's squad. Nullable until linked.
    provider_team_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)

    stats: Mapped[list[TeamStats]] = relationship(back_populates="team")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    name: Mapped[str] = mapped_column(String(20))  # "Group A"

    tournament: Mapped[Tournament] = relationship(back_populates="groups")
    group_teams: Mapped[list[GroupTeam]] = relationship(back_populates="group")
    standings: Mapped[list[Standing]] = relationship(back_populates="group")


class GroupTeam(Base):
    """Join table: which teams belong to which group."""

    __tablename__ = "group_teams"
    __table_args__ = (UniqueConstraint("group_id", "team_id", name="uq_group_team"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    group: Mapped[Group] = relationship(back_populates="group_teams")
    team: Mapped[Team] = relationship()


class Match(Base):
    """A scheduled WC2026 match (group or knockout)."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"))
    stage: Mapped[str] = mapped_column(String(20))  # group / R32 / R16 / QF / SF / third_place / final
    match_no: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)  # official KO match number (73..104)
    team_home_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    team_away_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(120))  # stadium name
    venue_city: Mapped[str | None] = mapped_column(String(80))
    venue_country: Mapped[str | None] = mapped_column(String(40))
    is_neutral: Mapped[bool] = mapped_column(default=True)
    # Set when a host nation plays in its own country -> drives the +60 Elo bonus (Decision #2).
    host_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled/in_play/finished
    score_home: Mapped[int | None] = mapped_column(Integer)
    score_away: Mapped[int | None] = mapped_column(Integer)
    # Regulation-time (90') score, frozen when a match first goes beyond
    # regulation and equal to the final score otherwise. The model predicts
    # 90-minute scores, so exact-score evaluation prefers this basis (FR-2.1).
    score_home_90: Mapped[int | None] = mapped_column(Integer)
    score_away_90: Mapped[int | None] = mapped_column(Integer)
    minute: Mapped[int | None] = mapped_column(Integer)  # live clock when in_play (None at HT/PENS)
    # Phase of play, refines `status` while in_play: first_half / half_time /
    # second_half / extra_time / penalty_shootout (None otherwise). Drives the
    # scoreboard label (HT / ET / PENS) since the free feed has no live minute.
    period: Mapped[str | None] = mapped_column(String(20))
    injury_time: Mapped[int | None] = mapped_column(Integer)  # added minutes, when the feed reports it
    penalty_home: Mapped[int | None] = mapped_column(Integer)  # shootout tally (score.penalties)
    penalty_away: Mapped[int | None] = mapped_column(Integer)
    # Feed's per-match version stamp (lastUpdated). A lagging cache node must not
    # overwrite a fresher record we already applied (see live_scores.update).
    provider_last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # API-Football fixture id, resolved on demand by the display-only lineups
    # endpoint (team-pair + kickoff date) and cached here so it can fetch
    # /fixtures/lineups without re-resolving each time.
    provider_fixture_id: Mapped[int | None] = mapped_column(Integer)
    # Goal events for the live/actual scoreline: ordered list of
    # {minute, side: "home"|"away", player, type: "goal"|"penalty"|"own_goal"}.
    # Populated by the api_football provider only (football-data has no scorers).
    goal_events: Mapped[list | None] = mapped_column(JSON)
    # Card events, same pipeline as goal_events: ordered list of
    # {minute, side: "home"|"away", player, type: "yellow"|"red"}. A second
    # yellow arrives from the feed as a single "red" event. Populated by the
    # api_football provider only (football-data has no cards) — None means
    # "no card data", which every consumer treats as zero cards.
    card_events: Mapped[list | None] = mapped_column(JSON)

    tournament: Mapped[Tournament] = relationship(back_populates="matches")
    group: Mapped[Group | None] = relationship(foreign_keys=[group_id])
    home_team: Mapped[Team | None] = relationship(foreign_keys=[team_home_id])
    away_team: Mapped[Team | None] = relationship(foreign_keys=[team_away_id])
    predictions: Mapped[list[Prediction]] = relationship(back_populates="match")
    lineups: Mapped[list[MatchLineup]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class MatchLineup(Base):
    """One team's announced lineup for a match (display-only; never feeds the
    prediction model). Fetched on demand from API-Football once a fixture is
    within its lineup window and cached permanently. UNIQUE(match_id, side)."""

    __tablename__ = "match_lineups"
    __table_args__ = (UniqueConstraint("match_id", "side", name="uq_match_lineup_side"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    side: Mapped[str] = mapped_column(String(4))  # "home" | "away"
    formation: Mapped[str | None] = mapped_column(String(20))  # e.g. "4-3-3"
    coach: Mapped[str | None] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(40))  # "api_football"
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    match: Mapped[Match] = relationship(back_populates="lineups")
    players: Mapped[list[LineupPlayer]] = relationship(
        back_populates="lineup", cascade="all, delete-orphan"
    )


class LineupPlayer(Base):
    """A single player within a MatchLineup (starter or bench). Display-only."""

    __tablename__ = "lineup_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_lineup_id: Mapped[int] = mapped_column(ForeignKey("match_lineups.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    number: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[str | None] = mapped_column(String(2))  # G/D/M/F
    grid: Mapped[str | None] = mapped_column(String(10))  # "row:col"; null for bench
    is_starter: Mapped[bool] = mapped_column(Boolean)
    # Stable sort within starter/bench (provider order). "order" is a reserved SQL
    # keyword, so the column is quoted; the attribute keeps the spec's name.
    order: Mapped[int] = mapped_column("order", Integer)
    # API-Football player id — links an announced XI row to a Player by id
    # (no fuzzy name matching). Nullable; older rows / unmatched players stay None.
    provider_player_id: Mapped[int | None] = mapped_column(Integer, index=True)

    lineup: Mapped[MatchLineup] = relationship(back_populates="players")


class Player(Base):
    """A squad player plus scoring stats, ingested from API-Football. Feeds the
    Phase 2 goalscorer model; never shown raw. Rates blend club-season form
    (season=2025) with WC-2026 form, so both are stored."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_player_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    position: Mapped[str | None] = mapped_column(String(2))  # G/D/M/F
    club_goals: Mapped[int | None] = mapped_column(Integer)
    club_minutes: Mapped[int | None] = mapped_column(Integer)
    club_penalties: Mapped[int | None] = mapped_column(Integer)
    wc_goals: Mapped[int | None] = mapped_column(Integer)
    wc_minutes: Mapped[int | None] = mapped_column(Integer)
    season: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HistoricalMatch(Base):
    """Past international results used for training (not shown directly in UI)."""

    __tablename__ = "historical_matches"
    __table_args__ = (
        UniqueConstraint(
            "date", "team_a_id", "team_b_id", name="uq_historical_match"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    score_a: Mapped[int] = mapped_column(Integer)
    score_b: Mapped[int] = mapped_column(Integer)
    competition: Mapped[str | None] = mapped_column(String(80))
    is_neutral: Mapped[bool] = mapped_column(default=False)
    venue: Mapped[str | None] = mapped_column(String(120))


class TeamStats(Base):
    __tablename__ = "team_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    as_of_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    matches_played: Mapped[int] = mapped_column(Integer, default=0)
    goals_for: Mapped[int] = mapped_column(Integer, default=0)
    goals_against: Mapped[int] = mapped_column(Integer, default=0)
    clean_sheets: Mapped[int] = mapped_column(Integer, default=0)
    form_points_last10: Mapped[float | None] = mapped_column(Float)
    xg_for: Mapped[float | None] = mapped_column(Float)
    xg_against: Mapped[float | None] = mapped_column(Float)

    team: Mapped[Team] = relationship(back_populates="stats")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    prob_home_win: Mapped[float] = mapped_column(Float)
    prob_draw: Mapped[float] = mapped_column(Float)
    prob_away_win: Mapped[float] = mapped_column(Float)
    predicted_score_home: Mapped[int | None] = mapped_column(Integer)
    predicted_score_away: Mapped[int | None] = mapped_column(Integer)
    predicted_score_prob: Mapped[float | None] = mapped_column(Float)
    # Pre-match engine params — feed the in-play win-prob model (app/live_winprob.py):
    # expected-goals rates (per 90) + Dixon-Coles rho, so the live bar reduces to
    # this prediction at kickoff.
    lambda_home: Mapped[float | None] = mapped_column(Float)
    lambda_away: Mapped[float | None] = mapped_column(Float)
    rho: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(10))  # High / Medium / Low
    reasons: Mapped[list | None] = mapped_column(JSON)
    top_features: Mapped[list | None] = mapped_column(JSON)

    match: Mapped[Match] = relationship(back_populates="predictions")


class Standing(Base):
    __tablename__ = "standings"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    played: Mapped[int] = mapped_column(Integer, default=0)
    won: Mapped[int] = mapped_column(Integer, default=0)
    drawn: Mapped[int] = mapped_column(Integer, default=0)
    lost: Mapped[int] = mapped_column(Integer, default=0)
    goals_for: Mapped[int] = mapped_column(Integer, default=0)
    goals_against: Mapped[int] = mapped_column(Integer, default=0)
    goal_diff: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    qualification_prob: Mapped[float | None] = mapped_column(Float)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    group: Mapped[Group] = relationship(back_populates="standings")
    team: Mapped[Team] = relationship()


class TournamentOdds(Base):
    """Per-team probabilities from the full-tournament Monte-Carlo (group stage
    through the knockout bracket): chance of reaching each round and winning."""

    __tablename__ = "tournament_odds"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), unique=True)
    make_knockout: Mapped[float | None] = mapped_column(Float)
    reach_r16: Mapped[float | None] = mapped_column(Float)
    reach_qf: Mapped[float | None] = mapped_column(Float)
    reach_sf: Mapped[float | None] = mapped_column(Float)
    reach_final: Mapped[float | None] = mapped_column(Float)
    win_title: Mapped[float | None] = mapped_column(Float)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    team: Mapped[Team] = relationship()


class PredictionResult(Base):
    """Prediction-vs-actual evaluation for one finished match (learning loop).

    Written once per finished match from the FROZEN pre-kickoff Prediction row
    (predictions are append-only and never regenerated after kickoff, so the
    latest row per match is the immutable snapshot). This table is the audited
    source of truth for the "AI record" endpoint and marketing claims.
    """

    __tablename__ = "prediction_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), unique=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    model_version: Mapped[str] = mapped_column(String(40))
    actual_score_home: Mapped[int] = mapped_column(Integer)
    actual_score_away: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(4))  # 'home' / 'draw' / 'away'
    winner_correct: Mapped[bool] = mapped_column(Boolean)
    exact_score_correct: Mapped[bool] = mapped_column(Boolean)
    prob_assigned: Mapped[float] = mapped_column(Float)  # p(actual outcome)
    brier: Mapped[float] = mapped_column(Float)
    log_loss: Mapped[float] = mapped_column(Float)
    goal_error: Mapped[int] = mapped_column(Integer)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    match: Mapped[Match] = relationship()
    prediction: Mapped[Prediction] = relationship()


class TeamTournamentState(Base):
    """Per-team in-tournament learning state (learning loop).

    Recomputed from scratch on every run by replaying finished WC matches from
    the historical Elo base (ml/ratings/tournament.py) — never incremental, so
    it cannot drift or double-apply. ``elo_delta + form_adjustment`` is added
    to ``teams.elo_rating`` wherever predictions/simulations read strength.
    ``detail`` keeps the per-match inputs for explainability.
    """

    __tablename__ = "team_tournament_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), unique=True)
    elo_delta: Mapped[float] = mapped_column(Float, default=0.0)
    form_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    gf_residual_mean: Mapped[float] = mapped_column(Float, default=0.0)
    ga_residual_mean: Mapped[float] = mapped_column(Float, default=0.0)
    matches_played: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    team: Mapped[Team] = relationship()


class Odds(Base):
    """Bookmaker odds. Historical odds are ingested for calibration only in MVP
    (Decision #1); user-facing odds comparison is Phase 4."""

    __tablename__ = "odds"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    bookmaker: Mapped[str | None] = mapped_column(String(60))
    odds_home: Mapped[float | None] = mapped_column(Float)
    odds_draw: Mapped[float | None] = mapped_column(Float)
    odds_away: Mapped[float | None] = mapped_column(Float)
    implied_prob_home: Mapped[float | None] = mapped_column(Float)
    implied_prob_draw: Mapped[float | None] = mapped_column(Float)
    implied_prob_away: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppUser(Base):
    """A signed-in user (first-party email+password identity).
    Accounts are an upgrade for anonymous players — never required to play."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str | None] = mapped_column(String(60))
    avatar_url: Mapped[str | None] = mapped_column(String(400))
    # Approx. geo at signup, from Vercel's edge headers (set when the request
    # came through the frontend proxy). Best-effort — null for direct API calls.
    signup_country: Mapped[str | None] = mapped_column(String(2))
    signup_city: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    bracket: Mapped[Bracket | None] = relationship(back_populates="user", uselist=False)
    match_picks: Mapped[list[MatchPick]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """An opaque server-side session. The browser holds only the raw token (in an
    HttpOnly cookie); we store its SHA-256 hash, so a DB leak can't be replayed."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_hash: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[AppUser] = relationship(back_populates="sessions")


class LoginAttempt(Base):
    """Per-email+IP login attempts, used to throttle credential stuffing."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    success: Mapped[bool] = mapped_column(Boolean, default=False)


class PasswordResetToken(Base):
    """A single-use, expiring password-reset token. The raw token is emailed in
    the link; only its SHA-256 hash is stored, so a DB leak can't reconstruct a
    usable link. used_at NULL = live; set on consume or invalidation."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip_hash: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[AppUser] = relationship()


class EmailActionAttempt(Base):
    """Records every reset / resend-verification / register request — even for
    unknown emails — so rate limiting is existence-agnostic: the limit can't be
    used to probe which accounts exist (tokens, which only exist for real users,
    can't)."""

    __tablename__ = "email_action_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class EmailVerificationToken(Base):
    """A single-use, expiring email-verification token. Mirrors
    PasswordResetToken (raw emailed in the link; only the SHA-256 hash stored).
    consumed_at NULL = live; set on use or on a sibling being consumed."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip_hash: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[AppUser] = relationship()


class Bracket(Base):
    """A user's saved bracket (one per user in the MVP)."""

    __tablename__ = "brackets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), unique=True, index=True)
    encoded_state: Mapped[str | None] = mapped_column(String(400))  # the ?b= share code
    champion_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    completion_pct: Mapped[float] = mapped_column(Float, default=0.0)
    visibility: Mapped[str] = mapped_column(String(10), default="private")  # private/public
    display_name: Mapped[str | None] = mapped_column(String(60))  # public leaderboard name
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[AppUser] = relationship(back_populates="bracket")
    champion: Mapped[Team | None] = relationship(foreign_keys=[champion_team_id])
    group_picks: Mapped[list[BracketGroupPick]] = relationship(
        back_populates="bracket", cascade="all, delete-orphan"
    )
    knockout_picks: Mapped[list[BracketKnockoutPick]] = relationship(
        back_populates="bracket", cascade="all, delete-orphan"
    )
    score: Mapped[BracketScore | None] = relationship(
        back_populates="bracket", uselist=False, cascade="all, delete-orphan"
    )


class BracketGroupPick(Base):
    __tablename__ = "bracket_group_picks"
    __table_args__ = (UniqueConstraint("bracket_id", "match_id", name="uq_bracket_group_pick"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bracket_id: Mapped[int] = mapped_column(ForeignKey("brackets.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    pick: Mapped[str] = mapped_column(String(4))  # home/draw/away
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bracket: Mapped[Bracket] = relationship(back_populates="group_picks")


class BracketKnockoutPick(Base):
    __tablename__ = "bracket_knockout_picks"
    __table_args__ = (UniqueConstraint("bracket_id", "match_no", name="uq_bracket_ko_pick"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    bracket_id: Mapped[int] = mapped_column(ForeignKey("brackets.id"), index=True)
    match_no: Mapped[int] = mapped_column(Integer)  # official knockout match number (73..104)
    picked_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    bracket: Mapped[Bracket] = relationship(back_populates="knockout_picks")


class BracketScore(Base):
    """Backend-computed score for a bracket (never trust the client)."""

    __tablename__ = "bracket_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    bracket_id: Mapped[int] = mapped_column(ForeignKey("brackets.id"), unique=True, index=True)
    group_points: Mapped[int] = mapped_column(Integer, default=0)
    knockout_points: Mapped[int] = mapped_column(Integer, default=0)
    champion_bonus: Mapped[int] = mapped_column(Integer, default=0)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int | None] = mapped_column(Integer)
    recalculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bracket: Mapped[Bracket] = relationship(back_populates="score")


class MatchPick(Base):
    """A signed-in user's per-match outcome pick (home/draw/away) — the account
    copy of the device-local match predictions, one row per (user, match)."""

    __tablename__ = "match_picks"
    __table_args__ = (UniqueConstraint("user_id", "match_id", name="uq_match_pick_user_match"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    pick: Mapped[str] = mapped_column(String(4))  # home/draw/away
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[AppUser] = relationship(back_populates="match_picks")


class LearningChainStatus(Base):
    """Single-row (id=1) heartbeat of the post-results chain.

    The chain runs opportunistically inside the web process after a final
    whistle, and its trigger sites swallow failures by design — so a crash (or
    the instance being killed mid-simulation) would otherwise be invisible and
    the finished match silently unprocessed. This row records every attempt /
    success / failure, plus ``covered_finished``: the finished-match count
    covered by the last COMPLETED chain. Current finished count > covered
    means work is owed — later refreshes retry it (app/live_refresh.py) and
    /api/health surfaces it. Accessors live in app/chain_status.py.
    """

    __tablename__ = "learning_chain_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_trigger: Mapped[str | None] = mapped_column(String(30))
    covered_finished: Mapped[int] = mapped_column(Integer, default=0)


__all__ = [
    "Tournament",
    "Team",
    "Group",
    "GroupTeam",
    "Match",
    "MatchLineup",
    "LineupPlayer",
    "Player",
    "HistoricalMatch",
    "TeamStats",
    "Prediction",
    "Standing",
    "TournamentOdds",
    "PredictionResult",
    "TeamTournamentState",
    "Odds",
    "AppUser",
    "UserSession",
    "LoginAttempt",
    "Bracket",
    "BracketGroupPick",
    "BracketKnockoutPick",
    "BracketScore",
    "MatchPick",
    "LearningChainStatus",
]
