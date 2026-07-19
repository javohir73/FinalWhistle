"""odds snapshot phase

Phased closing-line odds archive (pipeline/ingest/odds.py): tags each odds
row with the pre-kickoff band it was captured in (opening|t24|t6|t1|closing)
so the archive can hold up to 5 snapshots per match instead of one. Migration
only — nullable and unbackfilled, so every existing row (and every row from
the current single-snapshot refresh_odds/backfill_finished_odds callers)
reads as NULL, meaning legacy behavior is unaffected until the capture side
(a stacked PR) starts passing a phase.

Revision ID: 2985ca3c0a3a
Revises: 73ba3f9b0bf2
Create Date: 2026-07-19 18:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2985ca3c0a3a'
down_revision: Union[str, None] = '73ba3f9b0bf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("odds", sa.Column("snapshot_phase", sa.String(length=10), nullable=True))
    op.create_index("ix_odds_match_phase", "odds", ["match_id", "snapshot_phase"])


def downgrade() -> None:
    op.drop_index("ix_odds_match_phase", table_name="odds")
    op.drop_column("odds", "snapshot_phase")
