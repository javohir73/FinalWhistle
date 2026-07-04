"""add xg_a/xg_b to historical_matches

Additive, nullable Float columns — safe, no data change. Holds per-team
shot-xG (StatsBomb, periods 1-4 only, excludes penalty shootout) for the
shadow-only xG-nudged team-offsets fit. Absent xG stays NULL, never 0.0.

Revision ID: 0da36e4b28f3
Revises: d1e2f3a4b5c6
Create Date: 2026-07-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0da36e4b28f3"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("historical_matches", sa.Column("xg_a", sa.Float(), nullable=True))
    op.add_column("historical_matches", sa.Column("xg_b", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("historical_matches", "xg_b")
    op.drop_column("historical_matches", "xg_a")
