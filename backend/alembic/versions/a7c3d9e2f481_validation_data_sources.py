"""Independent validation data sources: fixture + market observation tables.

Purely additive. Creates two append-only tables and touches nothing existing:
the pre-registered `odds` baseline, the `market_odds_snapshots` product surface
and the in-flight `venue_market`/`entity_source_map` layer are all left alone.

Revision ID: a7c3d9e2f481
Revises: e1f2a3b4c5d6
Create Date: 2026-07-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7c3d9e2f481"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validation_fixture_observation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_event_id", sa.String(length=120), nullable=False),
        sa.Column("competition_code", sa.String(length=20), nullable=False),
        sa.Column("season", sa.String(length=20), nullable=True),
        sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_home_label", sa.String(length=160), nullable=False),
        sa.Column("raw_away_label", sa.String(length=160), nullable=False),
        sa.Column("canonical_home", sa.String(length=160), nullable=True),
        sa.Column("canonical_away", sa.String(length=160), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("score_home", sa.Integer(), nullable=True),
        sa.Column("score_away", sa.Integer(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("reconciliation_status", sa.String(length=20), nullable=False),
        sa.Column("reconciliation_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_event_id", "payload_sha256",
                            name="uq_validation_fixture_obs"),
    )
    op.create_index("ix_validation_fixture_observation_source",
                    "validation_fixture_observation", ["source"])
    op.create_index("ix_validation_fixture_match",
                    "validation_fixture_observation", ["match_id"])
    op.create_index("ix_validation_fixture_kickoff",
                    "validation_fixture_observation",
                    ["competition_code", "kickoff_utc"])

    op.create_table(
        "validation_market_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_market_id", sa.String(length=160), nullable=False),
        sa.Column("source_event_id", sa.String(length=120), nullable=True),
        sa.Column("competition_code", sa.String(length=20), nullable=False),
        sa.Column("kickoff_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_home_label", sa.String(length=160), nullable=False),
        sa.Column("raw_away_label", sa.String(length=160), nullable=False),
        sa.Column("canonical_home", sa.String(length=160), nullable=True),
        sa.Column("canonical_away", sa.String(length=160), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        # Empty-string default, never NULL: SQL treats NULLs as distinct, which
        # would silently defeat the uniqueness key for sources with no book.
        sa.Column("bookmaker_key", sa.String(length=60), nullable=False,
                  server_default=""),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("price_decimal", sa.Float(), nullable=True),
        sa.Column("implied_prob_raw", sa.Float(), nullable=True),
        sa.Column("implied_prob_devig", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("archive_sha256", sa.String(length=64), nullable=True),
        sa.Column("acquisition_note", sa.Text(), nullable=True),
        sa.Column("reconciliation_status", sa.String(length=20), nullable=False),
        sa.Column("reconciliation_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_market_id", "outcome",
                            "captured_at", "bookmaker_key",
                            name="uq_validation_market_snapshot"),
    )
    op.create_index("ix_validation_market_snapshot_source",
                    "validation_market_snapshot", ["source"])
    op.create_index("ix_validation_market_match",
                    "validation_market_snapshot", ["match_id"])
    op.create_index("ix_validation_market_captured",
                    "validation_market_snapshot", ["source", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_validation_market_captured", "validation_market_snapshot")
    op.drop_index("ix_validation_market_match", "validation_market_snapshot")
    op.drop_index("ix_validation_market_snapshot_source", "validation_market_snapshot")
    op.drop_table("validation_market_snapshot")
    op.drop_index("ix_validation_fixture_kickoff", "validation_fixture_observation")
    op.drop_index("ix_validation_fixture_match", "validation_fixture_observation")
    op.drop_index("ix_validation_fixture_observation_source",
                  "validation_fixture_observation")
    op.drop_table("validation_fixture_observation")
