"""Append-only store for operator-generated research artifacts.

Purely additive: one new table, nothing existing touched. Solves a delivery
dead end rather than adding a feature -- the research API reads a path that
production can never populate (image built with COPY, artifact gitignored,
free-tier container has no persistent disk, ephemeral runners cannot write
into it). Postgres is reachable from both sides via the DATABASE_URL that
already exists in Render and in GitHub Actions: no new service, no new
secret, no new cost.

Only small aggregate research JSON goes here. Raw venue payloads keep their
existing provenance path into the raw store and stay out of the database.

PostgreSQL-targeted like the rest of this chain; SQLite schemas in tests come
from Base.metadata.create_all.

Revision ID: e2f3a4b5c6d7
Revises: c2d3e4f5a6b7
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_artifact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("artifact_version", sa.String(length=60), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("published_by", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_research_artifact_size"),
        sa.CheckConstraint("length(sha256) = 64",
                           name="ck_research_artifact_digest"),
        sa.UniqueConstraint("kind", "sha256",
                            name="uq_research_artifact_content"),
    )
    op.create_index(
        "ix_research_artifact_kind_generated", "research_artifact",
        ["kind", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_artifact_kind_generated",
                  table_name="research_artifact")
    op.drop_table("research_artifact")
