"""add bridge signups

WC26 retention bridge: post-final "what's next" email capture, converting
World Cup traffic into NRL users now and a domestic-league launch list for
mid-August (see app/api/bridge.py). Migration-only PR — nothing calls the
endpoint until the frontend PR ships (CLAUDE.md migration sequencing).

Revision ID: 25690d8c48d1
Revises: 61673a6db4f2
Create Date: 2026-07-18 20:01:59.384763
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '25690d8c48d1'
down_revision: Union[str, None] = '61673a6db4f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bridge_signups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", "source", name="uq_bridge_signup_email_source"),
    )
    op.create_index("ix_bridge_signups_user_id", "bridge_signups", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_bridge_signups_user_id", table_name="bridge_signups")
    op.drop_table("bridge_signups")
