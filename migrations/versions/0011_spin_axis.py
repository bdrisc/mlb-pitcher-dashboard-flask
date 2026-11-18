"""Add official Statcast spin axis to pitches."""

import sqlalchemy as sa
from alembic import op

revision = "0011_spin_axis"
down_revision = "0010_published_pitching"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pitches", sa.Column("spin_axis", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("pitches", "spin_axis")
