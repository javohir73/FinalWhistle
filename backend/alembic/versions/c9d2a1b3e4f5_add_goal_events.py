"""add goal_events JSON column to matches

Revision ID: c9d2a1b3e4f5
Revises: a7c1f0e2d3b4
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d2a1b3e4f5"
down_revision: Union[str, None] = "a7c1f0e2d3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("goal_events", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "goal_events")
