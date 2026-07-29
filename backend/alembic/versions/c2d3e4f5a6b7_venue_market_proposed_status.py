"""venue_market.mapping_status gains 'proposed'.

A resolver review candidate is neither mapped (nothing verified it) nor
unmapped (there is a specific fixture under review, with an explanation).
Collapsing it into either loses the distinction the review queue runs on.

The downgrade must work on a table that HAS proposed rows: recreating the old
constraint over them would fail outright. Proposed rows return to 'unmapped'
-- their canonical columns are already NULL by construction and their
resolution_context / mapping_history evidence is untouched, so nothing is
lost except the status distinction the old schema cannot hold.

PostgreSQL-targeted, like the rest of this chain; SQLite schemas come from
Base.metadata.create_all in tests.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

_NAME = "ck_venue_market_mapping_status"
_TABLE = "venue_market"
_OLD = "mapping_status IN ('mapped', 'unmapped', 'ambiguous')"
_NEW = "mapping_status IN ('mapped', 'unmapped', 'ambiguous', 'proposed')"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_constraint(_NAME, _TABLE, type_="check")
    # Fold review candidates back into 'unmapped' BEFORE the old constraint
    # returns: their canonical columns are NULL by construction and their
    # resolution_context / mapping_history evidence stays intact.
    op.execute(sa.text(
        "UPDATE venue_market SET mapping_status = 'unmapped' "
        "WHERE mapping_status = 'proposed'"
    ))
    op.create_check_constraint(_NAME, _TABLE, _OLD)
