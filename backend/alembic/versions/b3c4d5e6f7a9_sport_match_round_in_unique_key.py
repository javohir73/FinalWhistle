"""Widen sport_matches unique key to include round.

The NRL feed's 2020 COVID-restart season restarts match_no within each
round (round 3 and round 5 can both have match_no=1, for distinct
fixtures). Match identity was wrongly keyed on (sport, season, match_no)
alone; the true key is (sport, season, round, match_no). Existing rows
can't violate the new, wider constraint since the old key was strictly
narrower (any two rows that were distinct under the old key are still
distinct under the new one).

Revision ID: b3c4d5e6f7a9
Revises: b2c3d4e5f6a8
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b3c4d5e6f7a9"
down_revision: Union[str, None] = "b2c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_sport_match_sport_season_no", "sport_matches", type_="unique")
    op.create_unique_constraint(
        "uq_sport_match_sport_season_round_no", "sport_matches",
        ["sport", "season", "round", "match_no"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sport_match_sport_season_round_no", "sport_matches", type_="unique")
    op.create_unique_constraint(
        "uq_sport_match_sport_season_no", "sport_matches", ["sport", "season", "match_no"],
    )
