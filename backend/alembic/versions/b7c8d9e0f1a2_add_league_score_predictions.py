"""add league score predictions (League Score Predictions design doc)

One new table for the football-league sibling of the NRL beat-the-AI loop:
league_score_predictions is one row per (match, player) scoreline guess,
upserted until kickoff and graded in place by a separate (pipeline-owned)
pass once each match finishes -- points/exact/graded_at start NULL and are
the only thing that pass ever writes. Reuses tip_players for identity (no
change to that table); league-generic via tournament_id, no EPL-only column.
Additive only -- no existing table's schema changes here (the matchweek
column on `matches` this feature also needs is a separate migration,
b7c8d9e0f1a2 -> c8d9e0f1a2b3, kept apart so this one stays exactly what the
spec's Data model section describes).

Per CLAUDE.md's migration sequencing, this must reach prod (refresh.yml,
`alembic upgrade head`) before the submit/read endpoints go live.

Revision ID: b7c8d9e0f1a2
Revises: a4b5c6d7e8f9
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "league_score_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tournament_id", sa.Integer(), sa.ForeignKey("tournaments.id"), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("tip_players.id"), nullable=False),
        sa.Column("predicted_home", sa.Integer(), nullable=False),
        sa.Column("predicted_away", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("exact", sa.Boolean(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("match_id", "player_id", name="uq_league_score_prediction_match_player"),
    )
    op.create_index(
        "ix_league_score_predictions_tournament_id", "league_score_predictions", ["tournament_id"],
    )
    op.create_index(
        "ix_league_score_predictions_match_id", "league_score_predictions", ["match_id"],
    )
    op.create_index(
        "ix_league_score_predictions_player_id", "league_score_predictions", ["player_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_league_score_predictions_player_id", table_name="league_score_predictions")
    op.drop_index("ix_league_score_predictions_match_id", table_name="league_score_predictions")
    op.drop_index("ix_league_score_predictions_tournament_id", table_name="league_score_predictions")
    op.drop_table("league_score_predictions")
