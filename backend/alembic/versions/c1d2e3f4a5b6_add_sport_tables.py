"""add sport_* tables for the multi-sport vertical (NRL first)

New, fully separate tables scoped by a `sport` column (e.g. "nrl") so NFL/NBA
can reuse the same schema later — no football table is touched. Mirrors the
football Team/Match/Prediction/PredictionResult shape: sport_teams, unique on
(sport, name); sport_matches, unique on (sport, season, match_no);
sport_predictions (is_shadow defaults true — new verticals ship shadow-only
until proven); sport_prediction_results, the evaluated record. Additive only.

Revision ID: c1d2e3f4a5b6
Revises: b5c6d7e8f9a0
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sport_teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("elo_rating", sa.Float(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.UniqueConstraint("sport", "name", name="uq_sport_team_sport_name"),
    )
    op.create_index("ix_sport_teams_sport", "sport_teams", ["sport"])

    op.create_table(
        "sport_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(length=10), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("match_no", sa.Integer(), nullable=False),
        sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("venue", sa.String(length=120), nullable=True),
        sa.Column("home_team_id", sa.Integer(), sa.ForeignKey("sport_teams.id"), nullable=True),
        sa.Column("away_team_id", sa.Integer(), sa.ForeignKey("sport_teams.id"), nullable=True),
        sa.Column("score_home", sa.Integer(), nullable=True),
        sa.Column("score_away", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.UniqueConstraint("sport", "season", "match_no", name="uq_sport_match_sport_season_no"),
    )
    op.create_index("ix_sport_matches_sport", "sport_matches", ["sport"])

    op.create_table(
        "sport_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("p_home", sa.Float(), nullable=False),
        sa.Column("p_draw", sa.Float(), nullable=False),
        sa.Column("p_away", sa.Float(), nullable=False),
        sa.Column("expected_margin", sa.Float(), nullable=True),
        sa.Column("is_shadow", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_sport_predictions_match_id", "sport_predictions", ["match_id"])

    op.create_table(
        "sport_prediction_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("prediction_id", sa.Integer(), sa.ForeignKey("sport_predictions.id"), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=4), nullable=False),
        sa.Column("winner_correct", sa.Boolean(), nullable=False),
        sa.Column("prob_assigned", sa.Float(), nullable=False),
        sa.Column("log_loss", sa.Float(), nullable=False),
        sa.Column("brier", sa.Float(), nullable=False),
        sa.Column("margin_error", sa.Float(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sport_prediction_results_match_id", "sport_prediction_results", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_sport_prediction_results_match_id", table_name="sport_prediction_results")
    op.drop_table("sport_prediction_results")
    op.drop_index("ix_sport_predictions_match_id", table_name="sport_predictions")
    op.drop_table("sport_predictions")
    op.drop_index("ix_sport_matches_sport", table_name="sport_matches")
    op.drop_table("sport_matches")
    op.drop_index("ix_sport_teams_sport", table_name="sport_teams")
    op.drop_table("sport_teams")
