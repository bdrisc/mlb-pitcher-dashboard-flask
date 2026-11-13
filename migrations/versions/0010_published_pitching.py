"""Store independently sourced pitcher-season references and handedness splits."""

import sqlalchemy as sa
from alembic import op

revision = "0010_published_pitching"
down_revision = "0009_expected_slg"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "published_pitching_metrics",
        sa.Column("mlb_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("batter_side", sa.String(length=3), nullable=False),
        sa.Column("fangraphs_id", sa.String(length=20), nullable=True),
        sa.Column("fip", sa.Float(), nullable=True),
        sa.Column("xfip", sa.Float(), nullable=True),
        sa.Column("siera", sa.Float(), nullable=True),
        sa.Column("xera", sa.Float(), nullable=True),
        sa.Column("fangraphs_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("savant_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("mlb_id", "season", "batter_side"),
    )


def downgrade():
    op.drop_table("published_pitching_metrics")
