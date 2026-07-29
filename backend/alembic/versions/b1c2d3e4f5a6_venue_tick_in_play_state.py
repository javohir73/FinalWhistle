"""venue_price_tick: arrival time, structured live state, transport out of the key.

Three changes, all on an empty table in every environment -- capture does not
exist yet.

1. `observed_at` (NOT NULL). `ts` is a LOGICAL time: for a stream tick it IS
   `source_ts`, so `ts - source_ts` is identically zero and any latency
   computed that way is a fiction. `created_at` is database insert time and
   drifts from arrival under buffering or replay, so it is not a substitute.

2. Structured live match state, with `in_play_state_supported` NOT NULL. A
   nullable capability would defeat its own guard: a CHECK expression that
   evaluates UNKNOWN passes, so a row with a NULL capability could carry a
   score the venue never published.

3. The primary key drops `transport`. One venue event delivered as `streaming`
   and redelivered as `recovery` is one observation; with transport in the key
   it took two rows and no constraint could see it. The `cycle:` / `event:`
   prefix on `observation_key` already separates the polling and stream
   families, so the key does not need transport -- which becomes
   first-delivery provenance.

PostgreSQL-targeted, like the rest of this chain (`e5f6a7b8c9d0` uses
`drop_constraint` and cannot run on SQLite at all). SQLite gets the columns;
its constraints and key come from `Base.metadata.create_all` in tests.

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
_PK = "pk_venue_price_tick"
_OLD_PK_COLUMNS = ["venue_market_id", "ts", "transport", "observation_key"]
_NEW_PK_COLUMNS = ["venue_market_id", "ts", "observation_key"]

#: Nullable additions. Absent detail is a real state ("venue reports live
#: state but had none for this observation"), so these stay nullable.
_NULLABLE_COLUMNS = (
    ("period", sa.String(length=40)),
    ("minute", sa.Float()),
    ("home_score", sa.Integer()),
    ("away_score", sa.Integer()),
    ("home_cards", sa.Integer()),
    ("away_cards", sa.Integer()),
)

#: NOT NULL additions. The server default only exists to let ADD COLUMN
#: succeed; it is dropped immediately so a writer that omits the value fails
#: loudly instead of inheriting a claim it never made.
_REQUIRED_COLUMNS = (
    ("observed_at", sa.DateTime(timezone=True), sa.func.now()),
    ("in_play_state_supported", sa.Boolean(), sa.false()),
)

_CONSTRAINTS = (
    (
        "ck_venue_price_tick_unsupported_state_is_empty",
        "in_play_state_supported = true OR ("
        "is_in_play IS NULL AND clock_state IS NULL"
        " AND period IS NULL AND minute IS NULL"
        " AND home_score IS NULL AND away_score IS NULL"
        " AND home_cards IS NULL AND away_cards IS NULL)",
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


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    for name, column_type in _NULLABLE_COLUMNS:
        op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))
    for name, column_type, default in _REQUIRED_COLUMNS:
        op.add_column(
            _TABLE,
            sa.Column(name, column_type, nullable=False, server_default=default),
        )
    if _sqlite():
        return
    for name, column_type, _default in _REQUIRED_COLUMNS:
        op.alter_column(_TABLE, name, existing_type=column_type, server_default=None)
    # Transport leaves the key and becomes provenance. Existing NOT NULL and
    # the transport CHECK are untouched.
    op.drop_constraint(_PK, _TABLE, type_="primary")
    op.create_primary_key(_PK, _TABLE, _NEW_PK_COLUMNS)
    for name, condition in _CONSTRAINTS:
        op.create_check_constraint(name, _TABLE, condition)


def downgrade() -> None:
    if not _sqlite():
        for name, _condition in reversed(_CONSTRAINTS):
            op.drop_constraint(name, _TABLE, type_="check")
        op.drop_constraint(_PK, _TABLE, type_="primary")
        op.create_primary_key(_PK, _TABLE, _OLD_PK_COLUMNS)
    for name, _column_type, _default in reversed(_REQUIRED_COLUMNS):
        op.drop_column(_TABLE, name)
    for name, _column_type in reversed(_NULLABLE_COLUMNS):
        op.drop_column(_TABLE, name)
