"""Store pre-match engine params on predictions (for live win prob).

The in-play win-probability model (backend/app/live_winprob.py) needs each
match's pre-match goal rates AND the Dixon-Coles rho to scale the remaining-time
Poisson so the live bar reduces exactly to the frozen pre-match prediction at
kickoff. We persist the two lambdas + rho the engine already computes. Nullable:
old prediction rows simply won't show a live bar until regenerated.

Revision ID: e0f1a2b3c4d5
Revises: c9d2a1b3e4f5
Create Date: 2026-06-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "c9d2a1b3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("lambda_home", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("lambda_away", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("rho", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "rho")
    op.drop_column("predictions", "lambda_away")
    op.drop_column("predictions", "lambda_home")
