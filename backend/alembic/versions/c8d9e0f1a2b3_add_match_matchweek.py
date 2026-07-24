"""add matches.matchweek (League Score Predictions design doc)

DEVIATION FLAGGED FOR REVIEW: the design doc's Data model section says this
feature needs exactly "one migration" and lists "No changes to tip_players,
matches, or any NRL table" -- but nothing in the schema today stores a
league fixture's matchweek/round number, and the tipsheet/leaderboard are
explicitly matchweek-scoped (Architecture: "Matchweek derivation... fixtures
carry round/matchweek from API-Football ingestion"). They do not: the raw
payload carries `league.round` (a string, e.g. "Regular Season - 5"), but
pipeline/ingest/league_structure.py's _fixture_fields never reads it, and no
existing Match column can hold it -- `stage` is repurposed (always "group"
for league fixtures) and `match_no` is UNIQUE table-wide (WC26 KO numbering),
so multiple fixtures in the same matchweek would collide on it.

This is a second, narrowly-scoped, additive-only migration (nullable column,
no backfill, no other table touched) rather than folding it into
b7c8d9e0f1a2 -- kept separate so that migration stays exactly what the spec
describes. The WRITE side (parsing `league.round` during league ingestion)
is NOT part of this change -- that's pipeline/ingest ownership; this only
adds the column + index the read side (app/api/league_score_predictions.py)
queries against. Coordinate before merge to avoid a duplicate column-add.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("matchweek", sa.Integer(), nullable=True))
    op.create_index("ix_matches_matchweek", "matches", ["matchweek"])


def downgrade() -> None:
    op.drop_index("ix_matches_matchweek", table_name="matches")
    op.drop_column("matches", "matchweek")
