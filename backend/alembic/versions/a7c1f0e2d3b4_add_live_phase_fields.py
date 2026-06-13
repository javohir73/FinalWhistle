"""add live phase fields to matches (period, injury time, penalties, freshness)

Revision ID: a7c1f0e2d3b4
Revises: f6a7b8c9d0e1
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1f0e2d3b4"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("period", sa.String(length=20), nullable=True))
    op.add_column("matches", sa.Column("injury_time", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("penalty_home", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("penalty_away", sa.Integer(), nullable=True))
    op.add_column(
        "matches",
        sa.Column("provider_last_updated", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matches", "provider_last_updated")
    op.drop_column("matches", "penalty_away")
    op.drop_column("matches", "penalty_home")
    op.drop_column("matches", "injury_time")
    op.drop_column("matches", "period")
