"""add prediction-market capture foundation

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-07-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TICK_PARTITIONS = (
    ("2026_07", "2026-07-01", "2026-08-01"),
    ("2026_08", "2026-08-01", "2026-09-01"),
    ("2026_09", "2026-09-01", "2026-10-01"),
    ("2026_10", "2026-10-01", "2026-11-01"),
    ("2026_11", "2026-11-01", "2026-12-01"),
    ("2026_12", "2026-12-01", "2027-01-01"),
    ("2027_01", "2027-01-01", "2027-02-01"),
    ("2027_02", "2027-02-01", "2027-03-01"),
    ("2027_03", "2027-03-01", "2027-04-01"),
    ("2027_04", "2027-04-01", "2027-05-01"),
    ("2027_05", "2027-05-01", "2027-06-01"),
    ("2027_06", "2027-06-01", "2027-07-01"),
    ("2027_07", "2027-07-01", "2027-08-01"),
    ("2027_08", "2027-08-01", "2027-09-01"),
    ("2027_09", "2027-09-01", "2027-10-01"),
    ("2027_10", "2027-10-01", "2027-11-01"),
    ("2027_11", "2027-11-01", "2027-12-01"),
    ("2027_12", "2027-12-01", "2028-01-01"),
)


def upgrade() -> None:
    op.create_table(
        "canonical_entity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sport", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('team', 'competition')", name="ck_canonical_entity_kind"
        ),
        sa.UniqueConstraint(
            "sport", "kind", "canonical_name", name="uq_canonical_entity_identity"
        ),
    )
    op.create_index("ix_canonical_entity_sport", "canonical_entity", ["sport"])
    op.create_index("ix_canonical_entity_kind", "canonical_entity", ["kind"])

    op.create_table(
        "entity_source_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_by", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_entity_source_map_confidence",
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["canonical_entity.id"]),
        sa.UniqueConstraint("source", "source_key", name="uq_entity_source_map_key"),
    )
    op.create_index("ix_entity_source_map_entity_id", "entity_source_map", ["entity_id"])

    op.create_table(
        "venue_market",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue", sa.String(length=40), nullable=False),
        sa.Column("venue_key", sa.String(length=255), nullable=False),
        sa.Column("sport", sa.String(length=20), nullable=False),
        sa.Column("market_type", sa.String(length=60), server_default="unknown", nullable=False),
        sa.Column("raw_title", sa.Text(), server_default="", nullable=False),
        sa.Column("raw_title_history", sa.JSON(), nullable=True),
        sa.Column("canonical_event_id", sa.Integer(), nullable=True),
        sa.Column("canonical_outcome", sa.String(length=160), nullable=True),
        sa.Column("mapping_status", sa.String(length=20), server_default="unmapped", nullable=False),
        sa.Column("resolution_context", sa.JSON(), nullable=True),
        sa.Column("mapping_history", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_outcome", sa.String(length=160), nullable=True),
        sa.Column("settlement_source", sa.String(length=500), nullable=True),
        sa.Column("settlement_source_event_id", sa.String(length=255), nullable=True),
        sa.Column("settlement_history", sa.JSON(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "mapping_status IN ('mapped', 'unmapped', 'ambiguous')",
            name="ck_venue_market_mapping_status",
        ),
        sa.CheckConstraint(
            "length(status) > 0", name="ck_venue_market_status_nonempty"
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR opened_at IS NULL OR closed_at >= opened_at",
            name="ck_venue_market_lifecycle",
        ),
        sa.CheckConstraint("last_seen >= first_seen", name="ck_venue_market_seen_order"),
        sa.UniqueConstraint("venue", "venue_key", name="uq_venue_market_key"),
    )
    op.create_index("ix_venue_market_sport", "venue_market", ["sport"])
    op.create_index("ix_venue_market_market_type", "venue_market", ["market_type"])
    op.create_index("ix_venue_market_canonical_event_id", "venue_market", ["canonical_event_id"])
    op.create_index("ix_venue_market_first_seen", "venue_market", ["first_seen"])
    op.create_index("ix_venue_market_last_seen", "venue_market", ["last_seen"])
    op.create_index(
        "ix_venue_market_mapping_coverage", "venue_market", ["venue", "mapping_status"]
    )
    op.create_index(
        "ix_venue_market_settlement_queue", "venue_market", ["status", "settled_at"]
    )

    op.create_table(
        "venue_price_tick",
        sa.Column("venue_market_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transport", sa.String(length=20), nullable=False),
        sa.Column("observation_key", sa.String(length=255), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column("scheduled_cycle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yes_bid", sa.Float(), nullable=True),
        sa.Column("yes_ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("mid", sa.Float(), nullable=True),
        sa.Column("bid_size", sa.Float(), nullable=True),
        sa.Column("ask_size", sa.Float(), nullable=True),
        sa.Column("book_top_n", sa.JSON(), nullable=True),
        sa.Column("is_in_play", sa.Boolean(), nullable=True),
        sa.Column("clock_state", sa.String(length=80), nullable=True),
        sa.Column("raw_payload_ref", sa.String(length=500), nullable=False),
        sa.Column("validation_flags", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "transport IN ('polling', 'streaming', 'recovery')",
            name="ck_venue_price_tick_transport",
        ),
        sa.CheckConstraint(
            "yes_bid IS NULL OR (yes_bid >= 0 AND yes_bid <= 1)",
            name="ck_venue_price_tick_yes_bid",
        ),
        sa.CheckConstraint(
            "yes_ask IS NULL OR (yes_ask >= 0 AND yes_ask <= 1)",
            name="ck_venue_price_tick_yes_ask",
        ),
        sa.CheckConstraint(
            "last IS NULL OR (last >= 0 AND last <= 1)",
            name="ck_venue_price_tick_last",
        ),
        sa.CheckConstraint(
            "mid IS NULL OR (mid >= 0 AND mid <= 1)",
            name="ck_venue_price_tick_mid",
        ),
        sa.CheckConstraint(
            "yes_bid IS NULL OR yes_ask IS NULL OR yes_bid <= yes_ask",
            name="ck_venue_price_tick_not_crossed",
        ),
        sa.CheckConstraint(
            "bid_size IS NULL OR bid_size > 0", name="ck_venue_price_tick_bid_size"
        ),
        sa.CheckConstraint(
            "ask_size IS NULL OR ask_size > 0", name="ck_venue_price_tick_ask_size"
        ),
        sa.ForeignKeyConstraint(["venue_market_id"], ["venue_market.id"]),
        sa.PrimaryKeyConstraint(
            "venue_market_id",
            "ts",
            "transport",
            "observation_key",
            name="pk_venue_price_tick",
        ),
        postgresql_partition_by="RANGE (ts)",
    )
    op.create_index(
        "ix_venue_price_tick_market_ts", "venue_price_tick", ["venue_market_id", "ts"]
    )
    op.create_index(
        "ix_venue_price_tick_transport_ts", "venue_price_tick", ["transport", "ts"]
    )

    if op.get_bind().dialect.name == "postgresql":
        for suffix, start, end in _TICK_PARTITIONS:
            op.execute(
                sa.text(
                    f"CREATE TABLE venue_price_tick_{suffix} "
                    "PARTITION OF venue_price_tick "
                    f"FOR VALUES FROM ('{start}') TO ('{end}')"
                )
            )
        op.execute(
            sa.text(
                "CREATE TABLE venue_price_tick_default "
                "PARTITION OF venue_price_tick DEFAULT"
            )
        )

    op.create_table(
        "capture_heartbeat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker", sa.String(length=120), nullable=False),
        sa.Column("venue", sa.String(length=40), nullable=False),
        sa.Column("scheduled_cycle_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intended_cadence_seconds", sa.Integer(), nullable=False),
        sa.Column("markets_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("success_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rate_limit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cycle_duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("markets_seen >= 0", name="ck_capture_heartbeat_markets_seen"),
        sa.CheckConstraint("success_count >= 0", name="ck_capture_heartbeat_success_count"),
        sa.CheckConstraint("error_count >= 0", name="ck_capture_heartbeat_error_count"),
        sa.CheckConstraint("retry_count >= 0", name="ck_capture_heartbeat_retry_count"),
        sa.CheckConstraint(
            "rate_limit_count >= 0", name="ck_capture_heartbeat_rate_limit_count"
        ),
        sa.CheckConstraint(
            "intended_cadence_seconds > 0", name="ck_capture_heartbeat_intended_cadence"
        ),
        sa.CheckConstraint(
            "cycle_duration_ms >= 0", name="ck_capture_heartbeat_cycle_duration"
        ),
        sa.CheckConstraint(
            "completed_at >= scheduled_cycle_at",
            name="ck_capture_heartbeat_completion_order",
        ),
        sa.UniqueConstraint(
            "worker", "venue", "scheduled_cycle_at", name="uq_capture_heartbeat_cycle"
        ),
    )
    op.create_index(
        "ix_capture_heartbeat_venue_cycle",
        "capture_heartbeat",
        ["venue", "scheduled_cycle_at"],
    )


def downgrade() -> None:
    op.drop_table("capture_heartbeat")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_table("venue_price_tick_default")
        for suffix, _start, _end in reversed(_TICK_PARTITIONS):
            op.drop_table(f"venue_price_tick_{suffix}")
    op.drop_table("venue_price_tick")
    op.drop_table("venue_market")
    op.drop_table("entity_source_map")
    op.drop_table("canonical_entity")
