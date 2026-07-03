"""add injuries column to matches

Additive, nullable JSON — safe, no data change. Holds the per-fixture
availability list feeding the day-ahead availability adjustment.

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b0
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c4d5e6f7a8b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("injuries", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "injuries")
