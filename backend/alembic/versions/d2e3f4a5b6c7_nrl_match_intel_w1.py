"""NRL match intelligence (Wave 1): margin/total/preview columns on
sport_predictions, and the nrl_projections finals table.

Wave 1 needs three additive columns for its own margin+total model output
(predicted_margin, predicted_total) and its deterministic prose generator
(preview_text) -- kept separate from the pre-existing expected_margin column,
which is the older Elo model's own margin estimate and stays untouched so
existing consumers (SportMatchCard, the NRL match page) don't change shape.
nrl_projections is a small, fully-replaced-each-refresh table (mirrors
probability_snapshots' delete-then-insert idiom) for the 5,000-run Monte
Carlo finals simulation: one row per team per refresh.

Revision ID: d2e3f4a5b6c7
Revises: c7d8e9f0a1b2
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sport_predictions", sa.Column("predicted_margin", sa.Float(), nullable=True))
    op.add_column("sport_predictions", sa.Column("predicted_total", sa.Float(), nullable=True))
    op.add_column("sport_predictions", sa.Column("preview_text", sa.Text(), nullable=True))

    op.create_table(
        "nrl_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team", sa.String(length=100), nullable=False),
        sa.Column("top8", sa.Float(), nullable=False),
        sa.Column("top4", sa.Float(), nullable=False),
        sa.Column("minor_premiership", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_nrl_projections_team", "nrl_projections", ["team"])


def downgrade() -> None:
    op.drop_index("ix_nrl_projections_team", table_name="nrl_projections")
    op.drop_table("nrl_projections")
    op.drop_column("sport_predictions", "preview_text")
    op.drop_column("sport_predictions", "predicted_total")
    op.drop_column("sport_predictions", "predicted_margin")
