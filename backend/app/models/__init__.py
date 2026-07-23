"""SQLAlchemy ORM models for the MVP tables (PRD §10).

Kept deliberately DB-agnostic (generic JSON, String for enums) so the same
models run on SQLite in tests and PostgreSQL in production. Phase 2+ tables
(players, injuries, live_events, social_sentiment, simulations) are added in
their own phases.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
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
    # League pivot D4: "host_bonus" (default — WC26's existing host-nation Elo
    # bonus, byte-identical) or "home" (a club league's real home advantage,
    # applied to team_home in every match regardless of host_team_id). See
    # pipeline/generate_predictions.py's _host_adv.
    home_advantage_mode: Mapped[str] = mapped_column(
        String(20), default="host_bonus", server_default="host_bonus"
    )
    # Tuned per-tournament home-advantage magnitude for the "home" mode (fit on
    # a holdout by log loss — pipeline/compute_club_elo.py). NULL means "use
    # the global engine params.home_adv"; irrelevant under "host_bonus".
    home_advantage_value: Mapped[float | None] = mapped_column(Float)

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
    # Per-fixture availability snapshot (day-ahead), same JSON pattern as
    # card_events: [{provider_player_id, name, type: "out"|"doubtful", reason, side}].
    # null = not yet ingested, [] = checked/clear.
    injuries: Mapped[list | None] = mapped_column(JSON)

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
    xg_a: Mapped[float | None] = mapped_column(Float)
    xg_b: Mapped[float | None] = mapped_column(Float)


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
    # Knockout resolution (stage != group, model v0.5): advance probabilities +
    # the win-90/extra-time/penalties path split (ml/models/knockout.py's
    # to_payload). NULL for group games and rows written before v0.5.
    knockout: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[str | None] = mapped_column(String(10))  # High / Medium / Low
    reasons: Mapped[list | None] = mapped_column(JSON)
    top_features: Mapped[list | None] = mapped_column(JSON)
    # Fable-style narrative sections (ml/explain/writeup.py): {case_home,
    # case_away, call, caveat}. Deterministic template over THIS row's numbers —
    # presentation only, never an input to anything. NULL for shadow twins
    # (internal-only, never rendered) and rows written before the feature.
    writeup: Mapped[dict | None] = mapped_column(JSON)
    # Shadow rows (exact-score program FR-4.4/4.5): the odds-anchored twin,
    # tagged model_version "poisson-elo-v0.3-shadow". Invisible to serving,
    # frozen-prediction selection, bracket scoring and the public record —
    # they exist only for the internal production-vs-shadow comparison.
    is_shadow: Mapped[bool] = mapped_column(default=False)

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

    Shadow scoring (FR-4.6) writes a SECOND row per match with is_shadow=True
    (the odds-anchored twin's evaluation, tagged its shadow model_version), so
    uniqueness is per (match, basis). Everything public reads is_shadow=False.
    """

    __tablename__ = "prediction_results"
    __table_args__ = (
        UniqueConstraint("match_id", "is_shadow", name="uq_prediction_result_match_shadow"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    model_version: Mapped[str] = mapped_column(String(40))
    is_shadow: Mapped[bool] = mapped_column(default=False)
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
    to ``teams.elo_rating`` wherever predictions/simulations read strength
    (unless the split form channels are active — see ``residual_ledger``).
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
    # Unified residual ledger (model v2 C1): time-ordered [gf_residual,
    # ga_residual] pairs, most recent last, optionally seeded with
    # pre-tournament history (ml.ratings.tournament.replay_tournament's
    # seed_ledgers). Feeds ml.ratings.form.form_offsets when
    # model_params.json ships a non-null form_channels; nullable and unused
    # otherwise (additive column, no backfill).
    # DEFERRED (deploy-window hardening): Render auto-deploys code before
    # refresh.yml applies migrations, so a plain column here would make every
    # full-entity SELECT (db.query(TeamTournamentState).all(), hit by
    # /api/internal/refresh-live every ~5 min mid-tournament) 500 against a DB
    # that hasn't been migrated yet. Deferred means SELECT * never includes
    # this column -- only an explicit .residual_ledger access does -- so those
    # request-time paths are safe regardless of migration timing. Paired with
    # the write-side gate in pipeline/learning_loop.update_tournament_state
    # (only touches this attribute when form_channels is enabled).
    residual_ledger: Mapped[list | None] = mapped_column(JSON, deferred=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    team: Mapped[Team] = relationship()


class Odds(Base):
    """Bookmaker odds — a MODEL INPUT only, never shown to users (PRD non-goal).

    Populated by the best-effort pre-kickoff snapshot (pipeline/ingest/odds.py,
    exact-score program FR-4.1): one consensus row per match per pass holding
    the MEDIAN decimal price across bookmakers for 1X2 and over/under-2.5,
    plus margin-free implied 1X2 probabilities. Feeds the shadow model's
    lambda-total anchor (ml/models/odds_blend.py)."""

    __tablename__ = "odds"
    __table_args__ = (
        Index("ix_odds_match_phase", "match_id", "snapshot_phase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    bookmaker: Mapped[str | None] = mapped_column(String(60))
    odds_home: Mapped[float | None] = mapped_column(Float)
    odds_draw: Mapped[float | None] = mapped_column(Float)
    odds_away: Mapped[float | None] = mapped_column(Float)
    odds_over25: Mapped[float | None] = mapped_column(Float)   # over 2.5 goals
    odds_under25: Mapped[float | None] = mapped_column(Float)  # under 2.5 goals
    implied_prob_home: Mapped[float | None] = mapped_column(Float)
    implied_prob_draw: Mapped[float | None] = mapped_column(Float)
    implied_prob_away: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # opening|t24|t6|t1|closing; NULL = legacy single-snapshot rows
    snapshot_phase: Mapped[str | None] = mapped_column(String(10))


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
    # Ops/smoke-test accounts: hidden from the public leaderboard and never
    # ranked. Set via POST /api/internal/flag-internal-user.
    is_internal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
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


class BridgeSignup(Base):
    """WC26 retention bridge (app/api/bridge.py): post-final "what's next" email
    capture, converting World Cup traffic into NRL users now and a
    domestic-league launch list for mid-August. UNIQUE(email, source) makes a
    resubmit idempotent rather than a duplicate row. user_id is best-effort —
    set only when the request carries a live session cookie."""

    __tablename__ = "bridge_signups"
    __table_args__ = (UniqueConstraint("email", "source", name="uq_bridge_signup_email_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # 255 matches every other email column in the repo (AppUser, LoginAttempt,
    # EmailActionAttempt) — the API layer rejects anything over 254 chars
    # before insert, so this never truncates.
    email: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(50))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DailyActivity(Base):
    """Anonymous device-level daily ping (app/api/activity.py): the source of
    truth for D7/D14 retention cohorts measured from the WC26 final
    (2026-07-19). UNIQUE(device_id, day) makes a same-day duplicate ping
    idempotent rather than a second row. Most traffic never signs up, so
    device_id — not user_id — is the cohort key; user_id is best-effort, set
    only when the request carries a live session cookie."""

    __tablename__ = "daily_activity"
    __table_args__ = (
        UniqueConstraint("device_id", "day", name="uq_daily_activity_device_day"),
        Index("ix_daily_activity_day", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --- Multi-sport vertical (NRL first; NFL/NBA share these same tables) ---
# `sport` scopes every row (e.g. "nrl", "nfl") so one schema serves all sports
# rather than repeating the football tables per sport. Mirrors the football
# Team/Match/Prediction/PredictionResult shape but kept fully separate — no
# football table is touched by this vertical.


class SportTeam(Base):
    __tablename__ = "sport_teams"
    __table_args__ = (UniqueConstraint("sport", "name", name="uq_sport_team_sport_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(100))
    elo_rating: Mapped[float | None] = mapped_column(Float)
    meta: Mapped[dict | None] = mapped_column(JSON)


class SportMatch(Base):
    __tablename__ = "sport_matches"
    __table_args__ = (
        # Identity key is (sport, season, round, match_no) — NOT (sport,
        # season, match_no) alone. Some feeds (e.g. NRL's 2020 COVID-restart
        # season) restart match_no within each round, so match_no by itself
        # is not unique within a season.
        UniqueConstraint(
            "sport", "season", "round", "match_no",
            name="uq_sport_match_sport_season_round_no",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10), index=True)
    season: Mapped[int] = mapped_column(Integer)
    round: Mapped[int | None] = mapped_column(Integer)
    match_no: Mapped[int] = mapped_column(Integer)
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(120))
    home_team_id: Mapped[int | None] = mapped_column(ForeignKey("sport_teams.id"))
    away_team_id: Mapped[int | None] = mapped_column(ForeignKey("sport_teams.id"))
    score_home: Mapped[int | None] = mapped_column(Integer)
    score_away: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled/finished


class SportPrediction(Base):
    __tablename__ = "sport_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    expected_margin: Mapped[float | None] = mapped_column(Float)
    # Wave 1 (NRL Match Intelligence): predicted_margin/predicted_total come
    # from the separately-fit ml.models.nrl_margin_total model (version
    # "nrl-elo-v0.2"), NOT from expected_margin (ml.sports.nrl.model's own
    # win-probability-model margin estimate, kept as-is so existing consumers
    # like SportMatchCard don't change shape). preview_text is the
    # deterministic prose preview, regenerated every nrl_predict --generate run.
    predicted_margin: Mapped[float | None] = mapped_column(Float)
    predicted_total: Mapped[float | None] = mapped_column(Float)
    preview_text: Mapped[str | None] = mapped_column(Text)
    # New verticals ship shadow-only until proven (mirrors predictions.is_shadow);
    # server_default so raw inserts (e.g. backfills) default true too.
    is_shadow: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class SportPredictionResult(Base):
    __tablename__ = "sport_prediction_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("sport_predictions.id"))
    model_version: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(4))  # home/draw/away
    winner_correct: Mapped[bool] = mapped_column(Boolean)
    prob_assigned: Mapped[float] = mapped_column(Float)
    log_loss: Mapped[float] = mapped_column(Float)
    brier: Mapped[float] = mapped_column(Float)
    margin_error: Mapped[float | None] = mapped_column(Float)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NrlProjection(Base):
    """Finals-projection snapshot (Wave 1): one row per team, fully replaced
    each nrl-refresh run by pipeline/sports/nrl_projections.py -- delete-then-
    insert at table granularity (no unique constraint needed, unlike
    ProbabilitySnapshot's per-day key) since every refresh replaces the whole
    table atomically."""
    __tablename__ = "nrl_projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    top8: Mapped[float] = mapped_column(Float)
    top4: Mapped[float] = mapped_column(Float)
    minor_premiership: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProbabilitySnapshot(Base):
    """Daily model-probability snapshots for movement deltas + sparklines.

    One row per (sport, entity, market, ref, day). Football entities are
    teams.id (markets: make_knockout / win_title / qualify_group); NRL
    entities are sport_teams.id with ref_id = sport_matches.id (win_match).
    """

    __tablename__ = "probability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "sport", "entity_id", "market", "ref_id", "snapshot_date",
            name="uq_prob_snapshot_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    market: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    prob: Mapped[float] = mapped_column(Float)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MarketOddsSnapshot(Base):
    """Hourly prediction-market odds (Polymarket / Kalshi) for the intel panel.

    Sport-scoped like ProbabilitySnapshot: match_id is matches.id for football
    and sport_matches.id for NRL; team_id likewise teams.id / sport_teams.id.
    Plain Integers (no FKs) because the referenced table depends on `sport`.
    Only ACTIVE (unresolved) exchange markets are ingested, so resolved or
    eliminated outcomes never appear here (spec 2026-07-10).
    """

    __tablename__ = "market_odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", "outcome", "fetched_at",
            name="uq_market_odds_key",
        ),
        Index("ix_market_odds_sport_fetched", "sport", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))  # polymarket / kalshi
    market_type: Mapped[str] = mapped_column(String(20))  # match_winner / title_winner
    match_id: Mapped[int | None] = mapped_column(Integer, index=True)
    team_id: Mapped[int | None] = mapped_column(Integer, index=True)
    outcome: Mapped[str] = mapped_column(String(10))  # home / draw / away / win
    implied_prob: Mapped[float] = mapped_column(Float)  # vig-normalized mid-price
    external_id: Mapped[str] = mapped_column(String(120))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --- Wave 2: NRL team-stats layer -------------------------------------------
# Table names nrl_match_stats / nrl_try_events are frozen by the match-intel
# program spec (Wave 3 builds on them). They deviate from the sport_* naming
# deliberately: the column set is rugby-league-specific.


class NrlMatchStat(Base):
    """One team's stat line for one finished NRL match (two rows per match)."""

    __tablename__ = "nrl_match_stats"
    __table_args__ = (
        UniqueConstraint("match_id", "team", name="uq_nrl_match_stats_match_team"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    tries: Mapped[int] = mapped_column(Integer)
    conversions: Mapped[int] = mapped_column(Integer)
    penalties_conceded: Mapped[int] = mapped_column(Integer)
    errors: Mapped[int] = mapped_column(Integer)
    set_restarts: Mapped[int] = mapped_column(Integer)
    run_metres: Mapped[int] = mapped_column(Integer)
    line_breaks: Mapped[int] = mapped_column(Integer)
    tackles: Mapped[int] = mapped_column(Integer)
    tackle_efficiency: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NrlTryEvent(Base):
    """One try event with running score (Wave 3's scorer model trains on these)."""

    __tablename__ = "nrl_try_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    player: Mapped[str] = mapped_column(String(120))
    minute: Mapped[int] = mapped_column(Integer)
    score_home: Mapped[int] = mapped_column(Integer)
    score_away: Mapped[int] = mapped_column(Integer)


class NrlTeamList(Base):
    """Weekly team-list announcement for one NRL match (Wave 3).

    One row per named player per team per match. Re-ingesting a match's list
    replaces the previous rows for that match; is_late_change flags a jersey
    slot whose named player differs from the previous ingest — never the
    very first announcement for that match (see pipeline/sports/nrl_team_lists.py).
    """
    __tablename__ = "nrl_team_lists"
    __table_args__ = (
        UniqueConstraint("match_id", "team", "jersey", name="uq_nrl_team_list_match_team_jersey"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    team: Mapped[str] = mapped_column(String(100))
    jersey: Mapped[int] = mapped_column(Integer)
    player: Mapped[str] = mapped_column(String(120))
    position: Mapped[str] = mapped_column(String(10))
    is_late_change: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NrlLiveState(Base):
    """Latest known live snapshot for one NRL match (Wave 3), upserted by
    pipeline.sports.nrl_live_poll. Absence of a row means the match has
    never been polled — the live endpoint falls back to a "pre"/"final"
    view derived from SportMatch + SportPrediction alone."""
    __tablename__ = "nrl_live_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(10))  # "live" | "final" (never "pre" — see docstring)
    minute: Mapped[int | None] = mapped_column(Integer)
    score_home: Mapped[int | None] = mapped_column(Integer)
    score_away: Mapped[int | None] = mapped_column(Integer)
    live_home_prob: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NrlLiveEvent(Base):
    """One scoring tick in an NRL match's live timeline (Wave 3)."""
    __tablename__ = "nrl_live_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    minute: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    team: Mapped[str] = mapped_column(String(10))  # "home" | "away"
    player: Mapped[str | None] = mapped_column(String(120))
    prob_after: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    "BridgeSignup",
    "DailyActivity",
    "SportTeam",
    "SportMatch",
    "SportPrediction",
    "SportPredictionResult",
    "NrlProjection",
    "ProbabilitySnapshot",
    "MarketOddsSnapshot",
    "NrlMatchStat",
    "NrlTryEvent",
    "NrlTeamList",
    "NrlLiveState",
    "NrlLiveEvent",
]
