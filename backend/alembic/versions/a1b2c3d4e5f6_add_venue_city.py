"""add venue_city to matches

Revision ID: a1b2c3d4e5f6
Revises: cc991b98094e
Create Date: 2026-06-07

Adds the city of the stadium so the UI can show "Stadium · City" and group
matches by venue. Stadium name lives in `venue`; this stores its city.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "cc991b98094e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("venue_city", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "venue_city")
