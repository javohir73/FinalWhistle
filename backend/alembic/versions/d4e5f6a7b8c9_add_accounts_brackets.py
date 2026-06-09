"""add user accounts, brackets, picks, and scores

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("auth_provider_user_id", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=True),
        sa.Column("avatar_url", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("auth_provider_user_id", name="uq_app_user_provider_id"),
    )
    op.create_index("ix_app_users_auth_provider_user_id", "app_users", ["auth_provider_user_id"])

    op.create_table(
        "brackets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id"), nullable=False),
        sa.Column("encoded_state", sa.String(length=400), nullable=True),
        sa.Column("champion_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("completion_pct", sa.Float(), server_default="0"),
        sa.Column("visibility", sa.String(length=10), server_default="private"),
        sa.Column("display_name", sa.String(length=60), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_bracket_user"),
    )
    op.create_index("ix_brackets_user_id", "brackets", ["user_id"])

    op.create_table(
        "bracket_group_picks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bracket_id", sa.Integer(), sa.ForeignKey("brackets.id"), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("pick", sa.String(length=4), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("bracket_id", "match_id", name="uq_bracket_group_pick"),
    )
    op.create_index("ix_bracket_group_picks_bracket_id", "bracket_group_picks", ["bracket_id"])

    op.create_table(
        "bracket_knockout_picks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bracket_id", sa.Integer(), sa.ForeignKey("brackets.id"), nullable=False),
        sa.Column("match_no", sa.Integer(), nullable=False),
        sa.Column("picked_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.UniqueConstraint("bracket_id", "match_no", name="uq_bracket_ko_pick"),
    )
    op.create_index("ix_bracket_knockout_picks_bracket_id", "bracket_knockout_picks", ["bracket_id"])

    op.create_table(
        "bracket_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bracket_id", sa.Integer(), sa.ForeignKey("brackets.id"), nullable=False),
        sa.Column("group_points", sa.Integer(), server_default="0"),
        sa.Column("knockout_points", sa.Integer(), server_default="0"),
        sa.Column("champion_bonus", sa.Integer(), server_default="0"),
        sa.Column("total_points", sa.Integer(), server_default="0"),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("bracket_id", name="uq_bracket_score"),
    )
    op.create_index("ix_bracket_scores_bracket_id", "bracket_scores", ["bracket_id"])


def downgrade() -> None:
    op.drop_table("bracket_scores")
    op.drop_table("bracket_knockout_picks")
    op.drop_table("bracket_group_picks")
    op.drop_table("brackets")
    op.drop_index("ix_app_users_auth_provider_user_id", table_name="app_users")
    op.drop_table("app_users")
