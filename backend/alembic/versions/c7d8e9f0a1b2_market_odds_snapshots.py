"""market odds snapshots (intel panel, spec 2026-07-10)

Revision ID: c7d8e9f0a1b2
Revises: b3c4d5e6f7a9
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b3c4d5e6f7a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_odds_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("implied_prob", sa.Float(), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "external_id", "outcome", "fetched_at",
                            name="uq_market_odds_key"),
    )
    op.create_index("ix_market_odds_snapshots_match_id",
                    "market_odds_snapshots", ["match_id"])
    op.create_index("ix_market_odds_snapshots_team_id",
                    "market_odds_snapshots", ["team_id"])
    op.create_index("ix_market_odds_sport_fetched",
                    "market_odds_snapshots", ["sport", "fetched_at"])


def downgrade() -> None:
    op.drop_table("market_odds_snapshots")
