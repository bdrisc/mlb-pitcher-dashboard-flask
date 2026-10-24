"""Store Statcast trajectory fits and raw plate approach angles."""

import sqlalchemy as sa
from alembic import op

revision = "0004_approach_angles"
down_revision = "0003_fangraphs_models"
branch_labels = None
depends_on = None

FIELDS = ("vx0", "vy0", "vz0", "ax", "ay", "az", "vaa", "haa")


def upgrade():
    for name in FIELDS:
        op.add_column("pitches", sa.Column(name, sa.Float(), nullable=True))
    op.add_column("pitches", sa.Column("approach_angle_version", sa.SmallInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table("pitches") as batch:
        batch.drop_column("approach_angle_version")
        for name in reversed(FIELDS):
            batch.drop_column(name)
