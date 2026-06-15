"""Store grouped scoreline probabilities on prediction rows.

Revision ID: c8d9e0f1a2b3
Revises: a7c1f0e2d3b4
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "a7c1f0e2d3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("scoreline_probs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "scoreline_probs")
