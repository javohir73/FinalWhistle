"""add signup geo (country/city) to app_users

Additive + nullable — safe, no data change. Populated on register from Vercel's
edge geo headers.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("signup_country", sa.String(length=2), nullable=True))
    op.add_column("app_users", sa.Column("signup_city", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("app_users", "signup_city")
    op.drop_column("app_users", "signup_country")
