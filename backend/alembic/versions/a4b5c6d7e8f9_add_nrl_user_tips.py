"""add NRL user tips (Beat-the-AI loop, Slice 2)

Two new, fully separate tables for the anonymous device-first tipping loop
(design doc: NRL Round Tips, Slice 2 -- Beat-the-AI loop). tip_players is the
device-keyed identity (mirrors daily_activity's device_id-first, user_id-
optional shape); user_tips is one row per (match, player) pick, upserted
until kickoff and graded in place by a separate pass once each match
finishes -- points/round_margin/graded_at start NULL and are the only thing
that pass ever writes. Additive only; no existing table is touched. Per
CLAUDE.md's migration sequencing, this must reach prod (refresh.yml or
nrl-refresh.yml, both run `alembic upgrade head`) before the submit/read
endpoints go live.

Revision ID: a4b5c6d7e8f9
Revises: 3f7a8b9c0d1e
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "3f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tip_players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("handle", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("device_id", name="uq_tip_players_device_id"),
        sa.UniqueConstraint("user_id", name="uq_tip_players_user_id"),
    )
    op.create_index("ix_tip_players_device_id", "tip_players", ["device_id"])
    op.create_index("ix_tip_players_user_id", "tip_players", ["user_id"])

    op.create_table(
        "user_tips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("sport_matches.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("tip_players.id"), nullable=False),
        sa.Column("pick", sa.String(length=4), nullable=False),
        sa.Column("margin", sa.Integer(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("round_margin", sa.Integer(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("match_id", "player_id", name="uq_user_tip_match_player"),
    )
    op.create_index("ix_user_tips_match_id", "user_tips", ["match_id"])
    op.create_index("ix_user_tips_player_id", "user_tips", ["player_id"])


def downgrade() -> None:
    op.drop_index("ix_user_tips_player_id", table_name="user_tips")
    op.drop_index("ix_user_tips_match_id", table_name="user_tips")
    op.drop_table("user_tips")
    op.drop_index("ix_tip_players_user_id", table_name="tip_players")
    op.drop_index("ix_tip_players_device_id", table_name="tip_players")
    op.drop_table("tip_players")
