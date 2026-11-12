"""Store Baseball Savant's per-batted-ball expected total bases."""

import sqlalchemy as sa
from alembic import op

revision = "0009_expected_slg"
down_revision = "0008_savant_woba"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pitches", sa.Column("estimated_slg", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("pitches") as batch:
        batch.drop_column("estimated_slg")
