"""add NRL shadow scoreline fields

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sport_predictions",
        sa.Column("predicted_score_home", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sport_predictions",
        sa.Column("predicted_score_away", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sport_predictions",
        sa.Column("score_model_version", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sport_predictions", "score_model_version")
    op.drop_column("sport_predictions", "predicted_score_away")
    op.drop_column("sport_predictions", "predicted_score_home")
