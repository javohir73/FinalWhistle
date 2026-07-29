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
    CheckConstraint,
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
    # League fixtures only (league score predictions design doc): the
    # matchweek/round number API-Football's fixture payload carries as
    # `league.round` (e.g. "Regular Season - 5" -> 5). NULL for WC26 rows and
    # for any league row ingested before this column existed. match_no can't
    # be repurposed for this -- it's globally UNIQUE (WC26 KO numbering) and
    # every fixture in a matchweek would collide on it. Populated by league
    # ingestion (pipeline/ingest/league_structure.py) -- not written here.
    #
    # DEFERRED (deploy-window hardening, same hazard as TeamTournamentState.
    # residual_ledger below): Render auto-deploys this code before refresh.yml
    # applies migration c8d9e0f1a2b3, so a plain column here would make every
    # full-entity Match SELECT -- /api/matches/upcoming polled every ~30s,
    # /api/tournaments/active, /api/knockout/bracket, and more -- 500 with
    # UndefinedColumn against a prod DB that hasn't been migrated yet.
    # Deferred means SELECT * never includes this column -- only the league
    # endpoints' explicit `Match.matchweek == ...` filters (which can't reach
    # a real row until the Premier League tournament itself is loaded,
    # post-migration/post-cutover) ever touch it, so the hot WC/live paths
    # stay safe regardless of migration timing.
    matchweek: Mapped[int | None] = mapped_column(Integer, index=True, deferred=True)
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
    # NRL score fields come from the fixture-specific shadow scoring model,
    # independently of expected_margin (the Elo W/D/L model's estimate).
    # Public APIs suppress them until the chronological MAE gate is promoted.
    predicted_margin: Mapped[float | None] = mapped_column(Float)
    predicted_total: Mapped[float | None] = mapped_column(Float)
    predicted_score_home: Mapped[int | None] = mapped_column(Integer)
    predicted_score_away: Mapped[int | None] = mapped_column(Integer)
    score_model_version: Mapped[str | None] = mapped_column(String(40))
    # Deterministic prose, regenerated every nrl_predict --generate run.
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


# --- Beat-the-AI loop (Slice 2): device-first tipping against the NRL model.
# Named tip_players/user_tips (not "nrl_tips") to stay distinct from
# app.api.nrl_tips, which is the model's OWN round tipsheet (GET-only, no
# player rows involved) -- these tables are the human side of the comparison.


class TipPlayer(Base):
    """A tipper's identity for the beat-the-AI loop. device_id-first, same
    shape as DailyActivity: most play never signs up, so the device id is the
    durable key and user_id is an optional upgrade attached later by the claim
    endpoint (unique -- an account merges into at most one player row).
    `handle` is an auto-generated readable display name (never the raw
    device_id), shown wherever a leaderboard needs a name."""

    __tablename__ = "tip_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    handle: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserTip(Base):
    """One player's pick for one sport_matches row. Upserted freely until the
    match's kickoff_utc (server clock, never trusted from the client -- see
    app/api/nrl_user_tips.py); `margin` is only ever set on the round's
    featured match. The last three columns are grading output, written by a
    separate pass hooked into nrl-refresh once the match is finished -- NULL
    until then, and this table's own API never fills them in."""

    __tablename__ = "user_tips"
    __table_args__ = (UniqueConstraint("match_id", "player_id", name="uq_user_tip_match_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("sport_matches.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("tip_players.id"), index=True)
    pick: Mapped[str] = mapped_column(String(4))  # home/draw/away
    margin: Mapped[int | None] = mapped_column(Integer)  # featured-match-only guess, 0..100
    # Snapshot of "was this the round's featured match" as of submit_tip's most
    # recent write to this row -- NULL on rows written before this column
    # existed (or written directly by a test fixture), in which case grade()
    # falls back to recomputing it live. Pinning it here means a later
    # fixture reschedule that changes the round's earliest kickoff can't
    # retroactively erase a margin the player legitimately entered (see
    # pipeline.sports.nrl_user_tips.grade()).
    is_featured: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # No onupdate=func.now() here -- submit_tip sets this explicitly on every
    # pick write, and grade()'s post-kickoff belt-and-braces filter (tip
    # eligible only if updated_at <= kickoff_utc) depends on it tracking ONLY
    # pick changes. An onupdate would also bump it on the grading pass's own
    # write and on /claim's player_id reassignment, both of which happen
    # after kickoff -- pushing updated_at past kickoff_utc and making the
    # filter wrongly exclude an already-locked, legitimately-graded tip.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Grading columns (nullable until the grading pass runs): 1 point for a
    # correct winner pick, or any pick at all if the match drew (comp-standard
    # scoring -- design doc: NRL Round Tips, Slice 2). round_margin is the
    # featured-match tiebreak value -- only ever set on that match's tip row.
    points: Mapped[int | None] = mapped_column(Integer)
    round_margin: Mapped[int | None] = mapped_column(Integer)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- League score predictions (League Score Predictions design doc,
# 2026-07-24): the football-league sibling of the NRL beat-the-AI loop above.
# Reuses tip_players for identity (same device-first, account-optional
# convention) instead of a second identity table -- POST /api/nrl/tips/claim
# already claims these rows too (see its second reassign/dedupe loop). Kept
# league-generic via tournament_id, matching every other surface in this
# feature (no EPL-only table/column).


class LeagueScorePrediction(Base):
    """One player's scoreline prediction for one football league match.
    Upserted freely until the match's kickoff_utc (server clock; see
    app/api/league_score_predictions.py's submit_prediction) -- keyed by
    match_id, not matchweek, so a fixture rescheduled into a different
    matchweek keeps its prediction. `exact` flags a 5-point row for the
    streak/summary UI without re-deriving it from points.

    No onupdate=func.now() on updated_at -- same NRL slice-2 lesson
    user_tips.updated_at's docstring explains: submit_prediction sets it
    explicitly on every pick write, and the (pipeline-owned) grading pass's
    post-kickoff eligibility filter (updated_at <= kickoff_utc) depends on it
    tracking ONLY pick changes -- an onupdate would also bump it on the
    grading pass's own write and on /claim's player_id reassignment, both of
    which happen after kickoff."""

    __tablename__ = "league_score_predictions"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_league_score_prediction_match_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("tip_players.id"), index=True)
    predicted_home: Mapped[int] = mapped_column(Integer)  # 0..15, validated at the API layer
    predicted_away: Mapped[int] = mapped_column(Integer)  # 0..15, validated at the API layer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Grading columns (nullable until the grading pass runs): 5 points for an
    # exact score, 2 for the correct result direction (win/draw/loss), 0
    # otherwise -- NOT cumulative (design doc). Idempotent-by-recompute, same
    # as user_tips.points -- see pipeline.sports.nrl_user_tips.grade() for the
    # pattern this table's (pipeline-owned) grading pass ports.
    points: Mapped[int | None] = mapped_column(Integer)
    exact: Mapped[bool | None] = mapped_column(Boolean)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


# --- Prediction-market intelligence layer ------------------------------------
# Additive shadow schema. The existing MarketOddsSnapshot path above remains
# live until the new capture path has proved coverage and correctness.


class CanonicalEntity(Base):
    """Venue-independent team or competition identity (P2 resolver target)."""

    __tablename__ = "canonical_entity"
    __table_args__ = (
        UniqueConstraint(
            "sport", "kind", "canonical_name", name="uq_canonical_entity_identity"
        ),
        CheckConstraint(
            "kind IN ('team', 'competition')", name="ck_canonical_entity_kind"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    canonical_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source_maps: Mapped[list[EntitySourceMap]] = relationship(back_populates="entity")


class EntitySourceMap(Base):
    """One exact, verified external key for a canonical entity."""

    __tablename__ = "entity_source_map"
    __table_args__ = (
        UniqueConstraint("source", "source_key", name="uq_entity_source_map_key"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_entity_source_map_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_entity.id"), index=True
    )
    source: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float | None] = mapped_column(Float)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    entity: Mapped[CanonicalEntity] = relationship(back_populates="source_maps")


class VenueMarket(Base):
    """Registry row for every discovered venue market, including unmapped ones."""

    __tablename__ = "venue_market"
    __table_args__ = (
        UniqueConstraint("venue", "venue_key", name="uq_venue_market_key"),
        CheckConstraint(
            "mapping_status IN ('mapped', 'unmapped', 'ambiguous')",
            name="ck_venue_market_mapping_status",
        ),
        CheckConstraint(
            "length(status) > 0", name="ck_venue_market_status_nonempty"
        ),
        CheckConstraint(
            "closed_at IS NULL OR opened_at IS NULL OR closed_at >= opened_at",
            name="ck_venue_market_lifecycle",
        ),
        CheckConstraint(
            "last_seen >= first_seen", name="ck_venue_market_seen_order"
        ),
        Index("ix_venue_market_mapping_coverage", "venue", "mapping_status"),
        Index("ix_venue_market_settlement_queue", "status", "settled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue: Mapped[str] = mapped_column(String(40))
    venue_key: Mapped[str] = mapped_column(String(255))
    sport: Mapped[str] = mapped_column(String(20), index=True)
    market_type: Mapped[str] = mapped_column(
        String(60), default="unknown", server_default="unknown", index=True
    )
    raw_title: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Preserve later title variants without rewriting the first observed title.
    raw_title_history: Mapped[list | None] = mapped_column(JSON)
    canonical_event_id: Mapped[int | None] = mapped_column(Integer, index=True)
    canonical_outcome: Mapped[str | None] = mapped_column(String(160))
    mapping_status: Mapped[str] = mapped_column(
        String(20), default="unmapped", server_default="unmapped"
    )
    # Explainable resolver output. Suggestions remain operator-only and can
    # never make a row serveable; mapping_history preserves every correction.
    resolution_context: Mapped[dict | None] = mapped_column(JSON)
    mapping_history: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_outcome: Mapped[str | None] = mapped_column(String(160))
    settlement_source: Mapped[str | None] = mapped_column(String(500))
    settlement_source_event_id: Mapped[str | None] = mapped_column(String(255))
    # Each item records the previous and replacement settlement plus provenance.
    settlement_history: Mapped[list | None] = mapped_column(JSON)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ticks: Mapped[list[VenuePriceTick]] = relationship(back_populates="market")


class VenuePriceTick(Base):
    """Append-only normalized quote with a pointer to the lossless raw payload."""

    __tablename__ = "venue_price_tick"
    __table_args__ = (
        CheckConstraint(
            "transport IN ('polling', 'streaming', 'recovery')",
            name="ck_venue_price_tick_transport",
        ),
        CheckConstraint(
            "yes_bid IS NULL OR (yes_bid >= 0 AND yes_bid <= 1)",
            name="ck_venue_price_tick_yes_bid",
        ),
        CheckConstraint(
            "yes_ask IS NULL OR (yes_ask >= 0 AND yes_ask <= 1)",
            name="ck_venue_price_tick_yes_ask",
        ),
        CheckConstraint(
            "last IS NULL OR (last >= 0 AND last <= 1)",
            name="ck_venue_price_tick_last",
        ),
        CheckConstraint(
            "mid IS NULL OR (mid >= 0 AND mid <= 1)",
            name="ck_venue_price_tick_mid",
        ),
        CheckConstraint(
            "yes_bid IS NULL OR yes_ask IS NULL OR yes_bid <= yes_ask",
            name="ck_venue_price_tick_not_crossed",
        ),
        CheckConstraint(
            "bid_size IS NULL OR bid_size > 0",
            name="ck_venue_price_tick_bid_size",
        ),
        CheckConstraint(
            "ask_size IS NULL OR ask_size > 0",
            name="ck_venue_price_tick_ask_size",
        ),
        # A venue that does not publish live match state may not imply any.
        # Without this, "unreported" and "reported as 0-0" share a row shape,
        # and a state-matched benchmark cannot say which it excluded.
        #
        # Stated positively, never as `NOT (supported = false AND ...)`: with a
        # nullable capability that form evaluates UNKNOWN, and a CHECK that
        # evaluates UNKNOWN passes. `in_play_state_supported` is therefore NOT
        # NULL and this expression is total -- a writer must declare the
        # capability, and cannot slip detail past the guard by omitting it.
        CheckConstraint(
            "in_play_state_supported = true OR ("
            "is_in_play IS NULL AND clock_state IS NULL"
            " AND period IS NULL AND minute IS NULL"
            " AND home_score IS NULL AND away_score IS NULL"
            " AND home_cards IS NULL AND away_cards IS NULL)",
            name="ck_venue_price_tick_unsupported_state_is_empty",
        ),
        CheckConstraint(
            "(home_score IS NULL) = (away_score IS NULL)",
            name="ck_venue_price_tick_score_pair",
        ),
        CheckConstraint(
            "(home_cards IS NULL) = (away_cards IS NULL)",
            name="ck_venue_price_tick_cards_pair",
        ),
        CheckConstraint(
            "(home_score IS NULL OR home_score >= 0)"
            " AND (away_score IS NULL OR away_score >= 0)"
            " AND (home_cards IS NULL OR home_cards >= 0)"
            " AND (away_cards IS NULL OR away_cards >= 0)",
            name="ck_venue_price_tick_counts_non_negative",
        ),
        CheckConstraint(
            "minute IS NULL OR minute >= 0",
            name="ck_venue_price_tick_minute",
        ),
        Index("ix_venue_price_tick_market_ts", "venue_market_id", "ts"),
        Index("ix_venue_price_tick_transport_ts", "transport", "ts"),
        # SQLite drops timezone information from returned datetime values, so
        # insertmanyvalues cannot match a timezone-aware composite-PK sentinel.
        # Inserts do not need RETURNING: every key field is supplied by capture.
        {"implicit_returning": False},
    )

    venue_market_id: Mapped[int] = mapped_column(
        ForeignKey("venue_market.id"), primary_key=True
    )
    # The logical observation time is stable across replay: scheduled cycle for
    # polling, venue event time for streaming/recovery. Including it in the
    # natural primary key permits PostgreSQL RANGE partitioning on this column.
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # OUR arrival time, kept because ts is a logical time and cannot carry it:
    # for a stream tick ts IS source_ts, so `ts - source_ts` is identically
    # zero and any latency computed that way is a fiction. Never identity.
    # Distinct from created_at, which is database insert time and drifts from
    # arrival under buffering, batching or replay.
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # First-delivery provenance, NOT part of the key. A single venue event
    # redelivered as `recovery` after arriving via `streaming` is one
    # observation; keying on transport would file it twice. Rows that read
    # `recovery` are exactly the events the stream missed.
    transport: Mapped[str] = mapped_column(String(20), nullable=False)
    # `event:<venue id>` or `cycle:<scheduled UTC timestamp>` from CONTRACTS.md.
    # The prefix already separates the polling and stream families, so the key
    # needs no transport component.
    observation_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255))
    scheduled_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    yes_bid: Mapped[float | None] = mapped_column(Float)
    yes_ask: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)
    mid: Mapped[float | None] = mapped_column(Float)
    bid_size: Mapped[float | None] = mapped_column(Float)
    ask_size: Mapped[float | None] = mapped_column(Float)
    book_top_n: Mapped[dict | None] = mapped_column(JSON)
    # Live match state, written as one block from InPlayState.as_columns().
    # `in_play_state_supported` is the venue's capability, not this tick's
    # luck: False means the venue never publishes match state, so downstream
    # comparisons exclude the tick and name the venue instead of reporting it
    # as a state disagreement. NOT NULL, so silence is never a third answer.
    in_play_state_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_in_play: Mapped[bool | None] = mapped_column(Boolean)
    clock_state: Mapped[str | None] = mapped_column(String(80))
    period: Mapped[str | None] = mapped_column(String(40))
    minute: Mapped[float | None] = mapped_column(Float)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    home_cards: Mapped[int | None] = mapped_column(Integer)
    away_cards: Mapped[int | None] = mapped_column(Integer)
    raw_payload_ref: Mapped[str] = mapped_column(String(500))
    validation_flags: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    market: Mapped[VenueMarket] = relationship(back_populates="ticks")


class CaptureHeartbeat(Base):
    """One worker/venue cycle; makes expected capture gaps queryable."""

    __tablename__ = "capture_heartbeat"
    __table_args__ = (
        UniqueConstraint(
            "worker", "venue", "scheduled_cycle_at", name="uq_capture_heartbeat_cycle"
        ),
        CheckConstraint("markets_seen >= 0", name="ck_capture_heartbeat_markets_seen"),
        CheckConstraint("success_count >= 0", name="ck_capture_heartbeat_success_count"),
        CheckConstraint("error_count >= 0", name="ck_capture_heartbeat_error_count"),
        CheckConstraint("retry_count >= 0", name="ck_capture_heartbeat_retry_count"),
        CheckConstraint(
            "rate_limit_count >= 0", name="ck_capture_heartbeat_rate_limit_count"
        ),
        CheckConstraint(
            "intended_cadence_seconds > 0",
            name="ck_capture_heartbeat_intended_cadence",
        ),
        CheckConstraint(
            "cycle_duration_ms >= 0", name="ck_capture_heartbeat_cycle_duration"
        ),
        CheckConstraint(
            "completed_at >= scheduled_cycle_at",
            name="ck_capture_heartbeat_completion_order",
        ),
        Index("ix_capture_heartbeat_venue_cycle", "venue", "scheduled_cycle_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker: Mapped[str] = mapped_column(String(120))
    venue: Mapped[str] = mapped_column(String(40))
    scheduled_cycle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    intended_cadence_seconds: Mapped[int] = mapped_column(Integer)
    markets_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rate_limit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cycle_duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[list | None] = mapped_column(JSON)
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
    "CanonicalEntity",
    "EntitySourceMap",
    "VenueMarket",
    "VenuePriceTick",
    "CaptureHeartbeat",
    "NrlMatchStat",
    "NrlTryEvent",
    "NrlTeamList",
    "NrlLiveState",
    "NrlLiveEvent",
]


# --- Independent validation data sources -------------------------------------
# Redundant fixture/result and market observations from providers OTHER than
# the one the served engine uses. Deliberately SEPARATE tables:
#
#   - `odds` is the pre-registered API-Football baseline the q3 confirmation
#     benchmark reads. Writing another provider there would silently change a
#     merged, pre-registered comparison, so nothing here ever touches it.
#   - `market_odds_snapshots` is the intel PRODUCT surface, replaced hourly and
#     swept by a retention prune. Evidence must not live behind a delete cycle.
#   - `venue_market`/`entity_source_map` have an unmerged resolver in flight;
#     a second writer with different conventions would collide.
#
# Both tables are APPEND-ONLY: a changed payload appends a new row rather than
# mutating one, so provenance is immutable and reruns are idempotent via the
# uniqueness keys. There is no retention sweep.


class ValidationFixtureObservation(Base):
    """One fixture/result as a single external provider reported it.

    Reconciliation input only. Never feeds ratings, predictions, or any served
    surface. One row per (source, event, payload) -- re-observing an unchanged
    fixture is a no-op; a corrected score appends a new row and leaves the
    original readable.
    """

    __tablename__ = "validation_fixture_observation"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_event_id", "payload_sha256",
            name="uq_validation_fixture_obs",
        ),
        Index("ix_validation_fixture_match", "match_id"),
        Index("ix_validation_fixture_kickoff", "competition_code", "kickoff_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: football_data_org | openligadb
    source: Mapped[str] = mapped_column(String(40), index=True)
    source_event_id: Mapped[str] = mapped_column(String(120))
    competition_code: Mapped[str] = mapped_column(String(20))
    season: Mapped[str | None] = mapped_column(String(20))
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Exactly as the provider spelled them, before any normalization.
    raw_home_label: Mapped[str] = mapped_column(String(160))
    raw_away_label: Mapped[str] = mapped_column(String(160))
    #: After this module's own alias mapping. NULL = could not be resolved.
    canonical_home: Mapped[str | None] = mapped_column(String(160))
    canonical_away: Mapped[str | None] = mapped_column(String(160))
    #: Nullable link to our Match. NULL is a normal, reportable state.
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    status: Mapped[str | None] = mapped_column(String(20))
    score_home: Mapped[int | None] = mapped_column(Integer)
    score_away: Mapped[int | None] = mapped_column(Integer)
    #: The provider's own last-updated stamp, when it publishes one.
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When WE retrieved it. Always set.
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    #: unmatched | matched | conflict
    reconciliation_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    reconciliation_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ValidationMarketSnapshot(Base):
    """One market price as a single external source reported it.

    SECONDARY benchmark evidence, reported per source and never merged into the
    pre-registered API-Football baseline. One finished match remains n=1 no
    matter how many sources, bookmakers or snapshots describe it.
    """

    __tablename__ = "validation_market_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_market_id", "outcome", "captured_at", "bookmaker_key",
            name="uq_validation_market_snapshot",
        ),
        Index("ix_validation_market_match", "match_id"),
        Index("ix_validation_market_captured", "source", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: the_odds_api | betfair_historical
    source: Mapped[str] = mapped_column(String(40), index=True)
    source_market_id: Mapped[str] = mapped_column(String(160))
    source_event_id: Mapped[str | None] = mapped_column(String(120))
    competition_code: Mapped[str] = mapped_column(String(20))
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_home_label: Mapped[str] = mapped_column(String(160))
    raw_away_label: Mapped[str] = mapped_column(String(160))
    canonical_home: Mapped[str | None] = mapped_column(String(160))
    canonical_away: Mapped[str | None] = mapped_column(String(160))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    #: Empty string (never NULL) so the uniqueness key stays effective -- SQL
    #: treats NULLs as distinct, which would silently defeat idempotency.
    bookmaker_key: Mapped[str] = mapped_column(String(60), default="", server_default="")
    outcome: Mapped[str] = mapped_column(String(10))  # home | draw | away
    price_decimal: Mapped[float | None] = mapped_column(Float)
    implied_prob_raw: Mapped[float | None] = mapped_column(Float)
    #: De-vigged WITHIN this source+market group only. Never blended across
    #: sources: a cross-source consensus would be a new predictor, not evidence.
    implied_prob_devig: Mapped[float | None] = mapped_column(Float)
    #: The source's own timestamp for this price. Admissibility is judged on
    #: THIS, never on retrieved_at.
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    #: Betfair only: digest of the operator-supplied archive, plus their note on
    #: where it came from. An importer-only source must still be citable.
    archive_sha256: Mapped[str | None] = mapped_column(String(64))
    acquisition_note: Mapped[str | None] = mapped_column(Text)
    reconciliation_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    reconciliation_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
