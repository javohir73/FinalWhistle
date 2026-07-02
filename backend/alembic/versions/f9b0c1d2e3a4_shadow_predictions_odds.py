"""Shadow predictions + over/under odds columns (exact-score program Phase 4)

predictions.is_shadow tags the odds-anchored twin rows (model_version
"poisson-elo-v0.3-shadow", FR-4.4) that serving, frozen-prediction selection,
bracket scoring and the public record all ignore (FR-4.5).
prediction_results.is_shadow holds the shadow model's own scored record
(FR-4.6) beside the production one, so the sole-row uniqueness moves from
match_id to (match_id, is_shadow). odds gains the over/under-2.5 prices the
market lambda-total inversion needs (FR-4.1/4.3). Additive apart from the
constraint widening — safe.

Revision ID: f9b0c1d2e3a4
Revises: e7f8a9b0c1d2
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9b0c1d2e3a4"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "predictions",
        sa.Column("is_shadow", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "prediction_results",
        sa.Column("is_shadow", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("odds", sa.Column("odds_over25", sa.Float(), nullable=True))
    op.add_column("odds", sa.Column("odds_under25", sa.Float(), nullable=True))
    # One result row per (match, basis): the shadow record lives beside the
    # production record. The old single-column unique came from unique=True in
    # the learning-loop migration, hence the default Postgres constraint name.
    op.drop_constraint("prediction_results_match_id_key", "prediction_results", type_="unique")
    op.create_unique_constraint(
        "uq_prediction_result_match_shadow", "prediction_results", ["match_id", "is_shadow"]
    )
    op.create_index(
        "ix_prediction_results_match_id", "prediction_results", ["match_id"]
    )


def downgrade() -> None:
    # Shadow rows violate the restored single-row-per-match invariant; they are
    # internal-only comparison data, so dropping them is the correct rollback.
    op.execute("DELETE FROM prediction_results WHERE is_shadow")
    op.execute("DELETE FROM predictions WHERE is_shadow")
    op.drop_index("ix_prediction_results_match_id", "prediction_results")
    op.drop_constraint("uq_prediction_result_match_shadow", "prediction_results", type_="unique")
    op.create_unique_constraint(
        "prediction_results_match_id_key", "prediction_results", ["match_id"]
    )
    op.drop_column("odds", "odds_under25")
    op.drop_column("odds", "odds_over25")
    op.drop_column("prediction_results", "is_shadow")
    op.drop_column("predictions", "is_shadow")
