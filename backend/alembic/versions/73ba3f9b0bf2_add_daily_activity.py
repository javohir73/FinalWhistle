"""add daily activity

Anonymous device-level daily ping (see app/api/activity.py): the source of
truth for D7/D14 retention cohorts measured from the WC26 final (2026-07-19).
Migration-only PR — the ping endpoint 500s until this runs, and nothing calls
it until the frontend PR ships (CLAUDE.md migration sequencing).

Revision ID: 73ba3f9b0bf2
Revises: 25690d8c48d1
Create Date: 2026-07-19 17:38:58.834151
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '73ba3f9b0bf2'
down_revision: Union[str, None] = '25690d8c48d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("device_id", "day", name="uq_daily_activity_device_day"),
    )
    op.create_index("ix_daily_activity_user_id", "daily_activity", ["user_id"])
    op.create_index("ix_daily_activity_day", "daily_activity", ["day"])


def downgrade() -> None:
    op.drop_index("ix_daily_activity_day", table_name="daily_activity")
    op.drop_index("ix_daily_activity_user_id", table_name="daily_activity")
    op.drop_table("daily_activity")
