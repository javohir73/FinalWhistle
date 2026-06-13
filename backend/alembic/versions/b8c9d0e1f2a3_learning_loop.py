"""Learning loop: prediction_results + team_tournament_state.

prediction_results stores the prediction-vs-actual evaluation per finished
match (winner/exact hits, Brier, log loss, goal error) — the audited "AI
record". team_tournament_state stores the per-team conservative Elo delta and
capped form adjustment replayed from finished WC2026 matches.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False, unique=True
        ),
        sa.Column(
            "prediction_id", sa.Integer(), sa.ForeignKey("predictions.id"), nullable=False
        ),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("actual_score_home", sa.Integer(), nullable=False),
        sa.Column("actual_score_away", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=4), nullable=False),
        sa.Column("winner_correct", sa.Boolean(), nullable=False),
        sa.Column("exact_score_correct", sa.Boolean(), nullable=False),
        sa.Column("prob_assigned", sa.Float(), nullable=False),
        sa.Column("brier", sa.Float(), nullable=False),
        sa.Column("log_loss", sa.Float(), nullable=False),
        sa.Column("goal_error", sa.Integer(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "team_tournament_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False, unique=True
        ),
        sa.Column("elo_delta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("form_adjustment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gf_residual_mean", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ga_residual_mean", sa.Float(), nullable=False, server_default="0"),
        sa.Column("matches_played", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("team_tournament_state")
    op.drop_table("prediction_results")
