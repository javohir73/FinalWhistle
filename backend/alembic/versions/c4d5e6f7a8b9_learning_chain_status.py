"""learning chain status heartbeat

Single-row table recording the post-results chain's last attempt / success /
failure and the finished-match count covered by the last COMPLETED chain.
Lets later refreshes and the daily pipeline retry chains that crashed or were
killed mid-run, and surfaces chain health in /api/health. Additive — safe.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a0
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b2c3d4e5f6a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_chain_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_trigger", sa.String(length=30), nullable=True),
        sa.Column("covered_finished", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("learning_chain_status")
