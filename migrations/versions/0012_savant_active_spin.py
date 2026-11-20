"""Store official spin-based active spin (spin efficiency) by pitcher and pitch type."""

import sqlalchemy as sa
from alembic import op

revision = "0012_savant_active_spin"
down_revision = "0011_spin_axis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "savant_active_spin",
        sa.Column("mlb_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("pitch_type", sa.String(length=4), nullable=False),
        sa.Column("active_spin_pct", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("mlb_id", "season", "pitch_type"),
    )


def downgrade():
    op.drop_table("savant_active_spin")
