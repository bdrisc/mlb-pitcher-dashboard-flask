"""Retain official Savant contact classification and source coverage."""

import sqlalchemy as sa
from alembic import op

revision = "0007_barrel_classification"
down_revision = "0006_vaa_adj"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pitches", sa.Column("launch_speed_angle", sa.SmallInteger(), nullable=True))
    op.add_column("pitches", sa.Column("barrel_checked", sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table("pitches") as batch:
        batch.drop_column("barrel_checked")
        batch.drop_column("launch_speed_angle")
