"""Store Savant's exact actual wOBA components."""

import sqlalchemy as sa
from alembic import op

revision = "0008_savant_woba"
down_revision = "0007_barrel_classification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pitches", sa.Column("savant_woba_numerator", sa.Float(), nullable=True))
    op.add_column("pitches", sa.Column("savant_woba_denominator", sa.SmallInteger(), nullable=True))


def downgrade():
    with op.batch_alter_table("pitches") as batch:
        batch.drop_column("savant_woba_denominator")
        batch.drop_column("savant_woba_numerator")
