"""Tournament home-advantage mode (league pivot D4)

Generalizes the WC2026 host bonus into a per-tournament setting so a club
competition can apply real home advantage instead. ``home_advantage_mode``
defaults to "host_bonus" everywhere (server_default), so every existing
WC26 row keeps its current behavior byte-identical — `_host_adv` in
pipeline/generate_predictions.py only takes the "home" branch (bonus to
team_home on every match, no host_team_id needed) when a tournament is
explicitly switched to it (the EPL league loader does this at creation).
``home_advantage_value`` is the tuned per-tournament magnitude for that
"home" branch (fit on a holdout by log loss, see pipeline/compute_club_elo.py);
NULL means "fall back to the global engine params.home_adv", which is the
right default until a tuning pass has run.

Revision ID: 3f7a8b9c0d1e
Revises: 2985ca3c0a3a
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3f7a8b9c0d1e"
down_revision: Union[str, None] = "2985ca3c0a3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column(
            "home_advantage_mode",
            sa.String(length=20),
            nullable=False,
            server_default="host_bonus",
        ),
    )
    op.add_column(
        "tournaments",
        sa.Column("home_advantage_value", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tournaments", "home_advantage_value")
    op.drop_column("tournaments", "home_advantage_mode")
