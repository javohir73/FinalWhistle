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
    stage: Mapped[str] = mapped_column(String(20))  # group / R32 / R16 / QF / SF / final
    team_home_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    team_away_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(120))  # stadium name
    venue_city: Mapped[str | None] = mapped_column(String(80))
    venue_country: Mapped[str | None] = mapped_column(String(40))
    is_neutral: Mapped[bool] = mapped_column(default=True)
    # Set when a host nation plays in its own country -> drives the +60 Elo bonus (Decision #2).
    host_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    score_home: Mapped[int | None] = mapped_column(Integer)
    score_away: Mapped[int | None] = mapped_column(Integer)

    tournament: Mapped[Tournament] = relationship(back_populates="matches")
    group: Mapped[Group | None] = relationship(foreign_keys=[group_id])
    home_team: Mapped[Team | None] = relationship(foreign_keys=[team_home_id])
    away_team: Mapped[Team | None] = relationship(foreign_keys=[team_away_id])
    predictions: Mapped[list[Prediction]] = relationship(back_populates="match")


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


__all__ = [
    "Tournament",
    "Team",
    "Group",
    "GroupTeam",
    "Match",
    "HistoricalMatch",
    "TeamStats",
    "Prediction",
    "Standing",
    "Odds",
]
