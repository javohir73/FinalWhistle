"""Structured live match state on venue_price_tick.

Purely additive and nullable. Adds the columns that let a tick say whether its
venue publishes live match state at all, separately from whether this
particular observation carried any. Without that distinction a state-matched
in-play benchmark cannot tell "the venue never reports a score" from "the score
disagrees", and reports zero coverage as if it were a model failure.

`venue_price_tick` is empty in every environment: capture does not exist yet.
The table is RANGE-partitioned on PostgreSQL, where ADD COLUMN and ADD
CONSTRAINT on the parent propagate to every partition.

Revision ID: b1c2d3e4f5a6
Revises: a7c3d9e2f481
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a7c3d9e2f481"
branch_labels = None
depends_on = None

_TABLE = "venue_price_tick"

_COLUMNS = (
    ("in_play_state_supported", sa.Boolean()),
    ("period", sa.String(length=40)),
    ("minute", sa.Float()),
    ("home_score", sa.Integer()),
    ("away_score", sa.Integer()),
    ("home_cards", sa.Integer()),
    ("away_cards", sa.Integer()),
)

_CONSTRAINTS = (
    (
        "ck_venue_price_tick_unsupported_state_is_empty",
        "NOT (in_play_state_supported = false AND ("
        "is_in_play IS NOT NULL OR clock_state IS NOT NULL"
        " OR period IS NOT NULL OR minute IS NOT NULL"
        " OR home_score IS NOT NULL OR away_score IS NOT NULL"
        " OR home_cards IS NOT NULL OR away_cards IS NOT NULL))",
    ),
    (
        "ck_venue_price_tick_score_pair",
        "(home_score IS NULL) = (away_score IS NULL)",
    ),
    (
        "ck_venue_price_tick_cards_pair",
        "(home_cards IS NULL) = (away_cards IS NULL)",
    ),
    (
        "ck_venue_price_tick_counts_non_negative",
        "(home_score IS NULL OR home_score >= 0)"
        " AND (away_score IS NULL OR away_score >= 0)"
        " AND (home_cards IS NULL OR home_cards >= 0)"
        " AND (away_cards IS NULL OR away_cards >= 0)",
    ),
    ("ck_venue_price_tick_minute", "minute IS NULL OR minute >= 0"),
)


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))
    # SQLite cannot ALTER TABLE ADD CONSTRAINT. Its schema comes from
    # Base.metadata.create_all in tests, which carries the same constraints.
    if op.get_bind().dialect.name != "sqlite":
        for name, condition in _CONSTRAINTS:
            op.create_check_constraint(name, _TABLE, condition)


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        for name, _condition in reversed(_CONSTRAINTS):
            op.drop_constraint(name, _TABLE, type_="check")
    for name, _column_type in reversed(_COLUMNS):
        op.drop_column(_TABLE, name)
