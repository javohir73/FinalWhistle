"""replace clerk identity with first-party email+password auth

Swaps AppUser.auth_provider_user_id for email + password_hash, and adds the
user_sessions and login_attempts tables. Pre-launch data is disposable: existing
accounts/brackets (the Clerk test row) are deleted so the new NOT NULL columns
add cleanly. Child rows are removed before parents to respect foreign keys.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pre-launch wipe — child rows first (no guaranteed cascade at the DB level).
    for table in (
        "bracket_scores",
        "bracket_knockout_picks",
        "bracket_group_picks",
        "brackets",
        "app_users",
    ):
        op.execute(f"DELETE FROM {table}")

    # AppUser: drop the Clerk identity column, add email+password identity.
    op.drop_index("ix_app_users_auth_provider_user_id", table_name="app_users")
    op.drop_constraint("uq_app_user_provider_id", "app_users", type_="unique")
    op.drop_column("app_users", "auth_provider_user_id")
    op.add_column("app_users", sa.Column("email", sa.String(length=255), nullable=False))
    op.add_column("app_users", sa.Column("password_hash", sa.String(length=255), nullable=False))
    op.add_column("app_users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_app_user_email", "app_users", ["email"])
    op.create_index("ix_app_users_email", "app_users", ["email"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_users.id"), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("session_token_hash", name="uq_user_session_token"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_session_token_hash", "user_sessions", ["session_token_hash"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("success", sa.Boolean(), server_default=sa.false()),
    )
    op.create_index("ix_login_attempts_email", "login_attempts", ["email"])
    op.create_index("ix_login_attempts_attempted_at", "login_attempts", ["attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_attempted_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_user_sessions_session_token_hash", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_app_users_email", table_name="app_users")
    op.drop_constraint("uq_app_user_email", "app_users", type_="unique")
    op.drop_column("app_users", "email_verified_at")
    op.drop_column("app_users", "password_hash")
    op.drop_column("app_users", "email")
    op.add_column("app_users", sa.Column("auth_provider_user_id", sa.String(length=120), nullable=False))
    op.create_unique_constraint("uq_app_user_provider_id", "app_users", ["auth_provider_user_id"])
    op.create_index("ix_app_users_auth_provider_user_id", "app_users", ["auth_provider_user_id"])
