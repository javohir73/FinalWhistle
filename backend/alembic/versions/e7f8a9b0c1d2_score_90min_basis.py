"""90-minute (regulation) score columns on matches

The Poisson model predicts 90-minute scores; knockout finals include extra
time. score_home_90/score_away_90 hold the regulation-time score — captured
live at the moment a match first goes beyond regulation, equal to the final
score when it doesn't — so exact-score evaluation can run on the basis the
model actually predicts (exact-score program FR-2.1). Additive — safe.

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("score_home_90", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("score_away_90", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "score_away_90")
    op.drop_column("matches", "score_home_90")
