"""Add matches.match_no.

Official knockout match number (73..104), nullable for group rows. Decouples
KO lookups from the previously-assumed DB-id == match_no coupling.

Revision ID: a1b2c3d4e5f9
Revises: f1a2b3c4d5e8
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, None] = "f1a2b3c4d5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("match_no", sa.Integer(), nullable=True))
    op.create_index("ix_matches_match_no", "matches", ["match_no"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_matches_match_no", table_name="matches")
    op.drop_column("matches", "match_no")
