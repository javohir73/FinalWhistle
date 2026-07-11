"""add writeup to predictions

Fable-style narrative sections for the match page (spec:
docs/superpowers/specs/2026-07-11-wc26-writeup-and-signal-readiness-design.md).
Nullable JSON — rows written before this feature simply have no writeup.
Migration-only PR: no code reads the column until it exists in prod
(CLAUDE.md migration sequencing).

Revision ID: 61673a6db4f2
Revises: 50c535d906b5
"""
from alembic import op
import sqlalchemy as sa

revision = "61673a6db4f2"
down_revision = "50c535d906b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("writeup", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("predictions", "writeup")
