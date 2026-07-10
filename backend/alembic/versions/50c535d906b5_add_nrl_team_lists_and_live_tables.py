"""add nrl_team_lists, nrl_live_state, nrl_live_events (Wave 3 player + live layer)

Revision ID: 50c535d906b5
Revises: d6e7f8a9b0c1
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "50c535d906b5"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nrl_team_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("jersey", sa.Integer(), nullable=False),
        sa.Column("player", sa.String(length=120), nullable=False),
        sa.Column("position", sa.String(length=10), nullable=False),
        sa.Column("is_late_change", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("match_id", "team", "jersey", name="uq_nrl_team_list_match_team_jersey"),
    )
    op.create_index("ix_nrl_team_lists_match_id", "nrl_team_lists", ["match_id"])

    op.create_table(
        "nrl_live_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=True),
        sa.Column("score_home", sa.Integer(), nullable=True),
        sa.Column("score_away", sa.Integer(), nullable=True),
        sa.Column("live_home_prob", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("match_id", name="uq_nrl_live_state_match_id"),
    )

    op.create_table(
        "nrl_live_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("team", sa.String(length=10), nullable=False),
        sa.Column("player", sa.String(length=120), nullable=True),
        sa.Column("prob_after", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_nrl_live_events_match_id", "nrl_live_events", ["match_id"])


def downgrade() -> None:
    op.drop_table("nrl_live_events")
    op.drop_table("nrl_live_state")
    op.drop_table("nrl_team_lists")
