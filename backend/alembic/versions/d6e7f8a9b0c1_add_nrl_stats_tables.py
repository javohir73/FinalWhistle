"""add nrl_match_stats + nrl_try_events (Wave 2 team-stats layer)

Revision ID: d6e7f8a9b0c1
Revises: d2e3f4a5b6c7
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nrl_match_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False),
        sa.Column("conversions", sa.Integer(), nullable=False),
        sa.Column("penalties_conceded", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("set_restarts", sa.Integer(), nullable=False),
        sa.Column("run_metres", sa.Integer(), nullable=False),
        sa.Column("line_breaks", sa.Integer(), nullable=False),
        sa.Column("tackles", sa.Integer(), nullable=False),
        sa.Column("tackle_efficiency", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("match_id", "team", name="uq_nrl_match_stats_match_team"),
    )
    op.create_index("ix_nrl_match_stats_match_id", "nrl_match_stats", ["match_id"])

    op.create_table(
        "nrl_try_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("player", sa.String(length=120), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("score_home", sa.Integer(), nullable=False),
        sa.Column("score_away", sa.Integer(), nullable=False),
    )
    op.create_index("ix_nrl_try_events_match_id", "nrl_try_events", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_nrl_try_events_match_id", table_name="nrl_try_events")
    op.drop_table("nrl_try_events")
    op.drop_index("ix_nrl_match_stats_match_id", table_name="nrl_match_stats")
    op.drop_table("nrl_match_stats")
