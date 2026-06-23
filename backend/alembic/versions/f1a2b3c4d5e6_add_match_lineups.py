"""Display-only match lineups: match_lineups + lineup_players, and the
matches.provider_fixture_id column.

Lineups are fetched on demand from API-Football once a fixture is within its
lineup window and cached permanently. They are display-only and never feed the
prediction model. provider_fixture_id caches the resolved API-Football fixture
id (by team-pair + kickoff date, or set by live ingestion) so the lineups
endpoint can fetch /fixtures/lineups without re-resolving each time.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-06-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("provider_fixture_id", sa.Integer(), nullable=True))
    op.create_table(
        "match_lineups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False, index=True),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("formation", sa.String(length=20), nullable=True),
        sa.Column("coach", sa.String(length=120), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("match_id", "side", name="uq_match_lineup_side"),
    )
    op.create_table(
        "lineup_players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "match_lineup_id",
            sa.Integer(),
            sa.ForeignKey("match_lineups.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("position", sa.String(length=2), nullable=True),
        sa.Column("grid", sa.String(length=10), nullable=True),
        sa.Column("is_starter", sa.Boolean(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lineup_players")
    op.drop_table("match_lineups")
    op.drop_column("matches", "provider_fixture_id")
