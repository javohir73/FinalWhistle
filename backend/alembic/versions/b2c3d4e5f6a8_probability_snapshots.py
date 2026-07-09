"""probability_snapshots for movers deltas + sparklines."""
import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a8"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "probability_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sport", sa.String(10), nullable=False, index=True),
        sa.Column("entity_id", sa.Integer, nullable=False, index=True),
        sa.Column("market", sa.String(30), nullable=False),
        sa.Column("ref_id", sa.Integer, nullable=True),
        sa.Column("prob", sa.Float, nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "sport", "entity_id", "market", "ref_id", "snapshot_date",
            name="uq_prob_snapshot_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("probability_snapshots")
