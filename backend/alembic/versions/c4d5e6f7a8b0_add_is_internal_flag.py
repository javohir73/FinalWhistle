"""add is_internal flag to app_users

Additive with a server default of false — safe, no data change. Internal
(smoke-test/ops) accounts are flagged via POST /api/internal/flag-internal-user
and excluded from the public leaderboard.

Revision ID: c4d5e6f7a8b0
Revises: b2c3d4e5f6a0
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b0"
down_revision: Union[str, None] = "b2c3d4e5f6a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_users",
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("app_users", "is_internal")
