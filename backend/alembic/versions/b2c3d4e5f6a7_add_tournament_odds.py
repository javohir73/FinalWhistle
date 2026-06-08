"""add tournament_odds (knockout simulation results)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-08

Per-team probabilities from the full-tournament Monte-Carlo: reaching each
knockout round and winning the title.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournament_odds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("make_knockout", sa.Float(), nullable=True),
        sa.Column("reach_r16", sa.Float(), nullable=True),
        sa.Column("reach_qf", sa.Float(), nullable=True),
        sa.Column("reach_sf", sa.Float(), nullable=True),
        sa.Column("reach_final", sa.Float(), nullable=True),
        sa.Column("win_title", sa.Float(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id"),
    )


def downgrade() -> None:
    op.drop_table("tournament_odds")
