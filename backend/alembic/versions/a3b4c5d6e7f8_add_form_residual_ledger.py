"""add residual_ledger to team_tournament_state

Additive, nullable JSON column — safe, no data change, no backfill. Holds the
unified time-ordered (gf_residual, ga_residual) ledger per team (model v2
C1, ml/ratings/tournament.py's TeamState.residual_ledger), consumed by
ml/ratings/form.py's split/decayed form offsets when model_params.json ships
a non-null form_channels. Absent ledger stays NULL; the learning loop
recomputes it from scratch on every run same as the other tournament-state
fields, so no backfill is needed.

Revision ID: a3b4c5d6e7f8
Revises: 0da36e4b28f3
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "0da36e4b28f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "team_tournament_state", sa.Column("residual_ledger", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("team_tournament_state", "residual_ledger")
