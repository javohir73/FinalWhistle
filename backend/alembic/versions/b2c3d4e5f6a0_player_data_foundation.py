"""Player data foundation.

Adds the players table plus provider id columns on teams and lineup_players,
for Phase 2 goalscorer predictions.

Revision ID: b2c3d4e5f6a0
Revises: a1b2c3d4e5f9
Create Date: 2026-06-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a0"
down_revision: Union[str, None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("provider_team_id", sa.Integer(), nullable=True))
    op.create_index("ix_teams_provider_team_id", "teams", ["provider_team_id"], unique=True)
    op.add_column("lineup_players", sa.Column("provider_player_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_lineup_players_provider_player_id", "lineup_players", ["provider_player_id"]
    )
    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_player_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("position", sa.String(length=2), nullable=True),
        sa.Column("club_goals", sa.Integer(), nullable=True),
        sa.Column("club_minutes", sa.Integer(), nullable=True),
        sa.Column("club_penalties", sa.Integer(), nullable=True),
        sa.Column("wc_goals", sa.Integer(), nullable=True),
        sa.Column("wc_minutes", sa.Integer(), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_players_provider_player_id", "players", ["provider_player_id"], unique=True)
    op.create_index("ix_players_team_id", "players", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_players_team_id", table_name="players")
    op.drop_index("ix_players_provider_player_id", table_name="players")
    op.drop_table("players")
    op.drop_index("ix_lineup_players_provider_player_id", table_name="lineup_players")
    op.drop_column("lineup_players", "provider_player_id")
    op.drop_index("ix_teams_provider_team_id", table_name="teams")
    op.drop_column("teams", "provider_team_id")
