"""add knockout block to predictions

Additive, nullable JSON column — safe, no data change, no backfill. Holds the
knockout resolution block for stage != group predictions (model v0.5,
ml/models/knockout.py's to_payload): advance probabilities and the
win-90/extra-time/penalties path split. Group games and pre-v0.5 rows stay
NULL; the serving layer treats NULL as "no block" so old rows need no
backfill (they are recomputable from the stored lambdas if ever wanted).

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("knockout", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "knockout")
